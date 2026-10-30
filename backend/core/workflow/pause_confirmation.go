package workflow

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"lazymind/core/common"
	"lazymind/core/common/orm"
	"lazymind/core/log"
	"lazymind/core/store"
	"lazymind/core/workflow/controlstore"
)

const (
	nativeStopLeaseDuration    = 30 * time.Second
	nativeStopRecoveryGrace    = 30 * time.Second
	nativeStopRecoveryInterval = 5 * time.Second
)

// PauseNativeWorkflowHTTP pauses only the selected native session, never its
// containing Chat. Use the same executor acknowledgement path as Chat pause.
func PauseNativeWorkflowHTTP(w http.ResponseWriter, r *http.Request) {
	if !IsWorkflowUserControlRequest(r) {
		writeWorkflowControlError(w, controlstore.Reject("PERMISSION_DENIED", "pause requires an authenticated browser request"))
		return
	}
	db := store.DB()
	var session orm.WorkflowSession
	if err := db.WithContext(r.Context()).Where("id = ? AND create_user_id = ? AND dismissed = false",
		common.PathVar(r, "session_id"), r.Header.Get("X-User-Id")).First(&session).Error; err != nil {
		writeWorkflowControlError(w, err)
		return
	}
	if session.ControllerHost != "lazymind" || controlstore.Controlled(session) {
		writeWorkflowControlError(w, controlstore.Reject("CONTROL_PROTOCOL_REQUIRED", "use the workflow host controls for this session"))
		return
	}
	if err := stopWorkflowSession(r.Context(), db, store.State(), &session, ""); err != nil {
		writeWorkflowControlError(w, err)
		return
	}
	common.ReplyOK(w, nil)
}

// ConfirmNativeStop is a completion receipt, not a cancellation request. The
// worker calls it after its executor (including tools and cleanup) has exited.
// The old lease token identifies that exact execution even after it was fenced.
func ConfirmNativeStop(ctx context.Context, db *gorm.DB, attemptID, token string) error {
	return db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		var step orm.WorkflowSessionStep
		if err := tx.Where("id = ?", attemptID).First(&step).Error; err != nil {
			return err
		}
		var session orm.WorkflowSession
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where("id = ?", step.SessionID).First(&session).Error; err != nil {
			return err
		}
		if controlstore.Controlled(session) || session.ControllerHost != "lazymind" {
			return nil
		}
		// Re-read under the session lock, shared by stop and lease transitions.
		if err := tx.Where("id = ?", attemptID).First(&step).Error; err != nil {
			return err
		}
		if step.LeaseToken != token {
			return controlstore.Reject("LEASE_LOST", "stop receipt belongs to a different execution")
		}
		_, err := finalizeNativeStop(tx, &session, &step, "executor_ack", time.Now().UTC())
		return err
	})
}

// finalizeNativeStop is the single terminal transition for both an executor
// receipt and lease-expiry recovery. Callers must hold the session lock.
func finalizeNativeStop(
	tx *gorm.DB,
	session *orm.WorkflowSession,
	step *orm.WorkflowSessionStep,
	confirmationSource string,
	now time.Time,
) (bool, error) {
	changed := false
	result := tx.Model(&orm.WorkflowSessionStep{}).
		Where("id = ? AND terminal_code = ?", step.ID, "WORKFLOW_STOP_REQUESTED").
		Updates(map[string]any{
			"terminal_code":    "WORKFLOW_STOPPED",
			"lease_expires_at": nil,
			"updated_at":       now,
		})
	if result.Error != nil {
		return false, result.Error
	}
	if result.RowsAffected > 0 {
		changed = true
		step.TerminalCode = "WORKFLOW_STOPPED"
		step.LeaseExpiresAt = nil
		step.UpdatedAt = now
	}
	outbox := tx.Model(&orm.WorkflowOutbox{}).
		Where("attempt_id = ? AND status IN ?", step.ID, []string{"pending", "claimed"}).
		Updates(map[string]any{"status": "cancelled", "updated_at": now})
	if outbox.Error != nil {
		return false, outbox.Error
	}
	changed = changed || outbox.RowsAffected > 0

	var pending int64
	if err := tx.Model(&orm.WorkflowSessionStep{}).
		Where("session_id = ? AND terminal_code = ?", session.ID, "WORKFLOW_STOP_REQUESTED").
		Count(&pending).Error; err != nil {
		return false, err
	}
	if pending > 0 || session.Status != "pausing" {
		return changed, nil
	}
	session.Status = SessionStatusWaiting
	session.StateVersion++
	session.UpdatedAt = now
	if err := tx.Model(session).Updates(map[string]any{
		"status": session.Status, "state_version": session.StateVersion, "updated_at": session.UpdatedAt,
	}).Error; err != nil {
		return false, err
	}
	payload, _ := json.Marshal(map[string]any{
		"status":              SessionStatusWaiting,
		"user_stopped":        true,
		"confirmation_source": confirmationSource,
	})
	if err := appendSessionStateEvent(tx, *session, "workflow.patch", payload); err != nil {
		return false, err
	}
	return true, nil
}

func nativeStopRecoveryDeadline(
	step orm.WorkflowSessionStep,
	session orm.WorkflowSession,
	grace time.Duration,
) time.Time {
	if grace <= 0 {
		grace = nativeStopRecoveryGrace
	}
	if step.LeaseExpiresAt != nil {
		return step.LeaseExpiresAt.Add(grace)
	}
	// Compatibility for sessions created by the old stop path, which erased
	// lease_expires_at. Use the newest durable liveness timestamp and allow one
	// full lease window plus grace before declaring the vanished executor fenced.
	base := step.UpdatedAt
	if step.HeartbeatAt != nil && step.HeartbeatAt.After(base) {
		base = *step.HeartbeatAt
	}
	if session.LastStoppedAt != nil && session.LastStoppedAt.After(base) {
		base = *session.LastStoppedAt
	}
	return base.Add(nativeStopLeaseDuration + grace)
}

// ReconcileNativeStops completes stop requests whose executor can no longer
// renew its fenced lease. It never reclaims or reruns the stopped attempt.
func ReconcileNativeStops(
	ctx context.Context,
	db *gorm.DB,
	now time.Time,
	grace time.Duration,
) (int, error) {
	if db == nil {
		return 0, nil
	}
	var attemptIDs []string
	if err := db.WithContext(ctx).Model(&orm.WorkflowSessionStep{}).
		Joins("JOIN plugin_sessions ps ON ps.id = plugin_session_steps.session_id").
		Where("ps.status = ? AND ps.controller_host = ? AND plugin_session_steps.terminal_code = ? AND plugin_session_steps.status IN ?",
			"pausing", "lazymind", "WORKFLOW_STOP_REQUESTED", []string{StepStatusInterrupted, "cancelled", "canceled"}).
		Pluck("plugin_session_steps.id", &attemptIDs).Error; err != nil {
		return 0, err
	}
	recovered := 0
	for _, attemptID := range attemptIDs {
		changed := false
		err := db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
			var step orm.WorkflowSessionStep
			if err := tx.Where("id = ?", attemptID).First(&step).Error; err != nil {
				return err
			}
			var session orm.WorkflowSession
			if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where("id = ?", step.SessionID).First(&session).Error; err != nil {
				return err
			}
			if controlstore.Controlled(session) || session.ControllerHost != "lazymind" || session.Status != "pausing" {
				return nil
			}
			if err := tx.Where("id = ?", attemptID).First(&step).Error; err != nil {
				return err
			}
			if step.TerminalCode != "WORKFLOW_STOP_REQUESTED" ||
				(step.Status != StepStatusInterrupted && step.Status != "cancelled" && step.Status != "canceled") ||
				now.Before(nativeStopRecoveryDeadline(step, session, grace)) {
				return nil
			}
			var err error
			changed, err = finalizeNativeStop(tx, &session, &step, "lease_expired", now)
			return err
		})
		if err != nil {
			return recovered, err
		}
		if changed {
			recovered++
		}
	}
	return recovered, nil
}

// StartNativeStopRecovery repairs stale pausing sessions once at startup and
// then periodically. The returned channel closes when ctx is cancelled.
func StartNativeStopRecovery(ctx context.Context, db *gorm.DB) <-chan struct{} {
	done := make(chan struct{})
	go func() {
		defer close(done)
		run := func(now time.Time) {
			count, err := ReconcileNativeStops(ctx, db, now.UTC(), nativeStopRecoveryGrace)
			if err != nil {
				log.Logger.Warn().Err(err).Msg("reconcile native Workflow stops failed")
			} else if count > 0 {
				log.Logger.Info().Int("count", count).Msg("reconciled native Workflow stops")
			}
		}
		run(time.Now())
		ticker := time.NewTicker(nativeStopRecoveryInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case now := <-ticker.C:
				run(now)
			}
		}
	}()
	return done
}

func ConfirmNativeStopHTTP(w http.ResponseWriter, r *http.Request) {
	var req struct {
		LeaseToken string `json:"lease_token"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.LeaseToken == "" {
		common.ReplyErr(w, "lease_token required", http.StatusBadRequest)
		return
	}
	if err := ConfirmNativeStop(r.Context(), store.DB(), common.PathVar(r, "attempt_id"), req.LeaseToken); err != nil {
		writeWorkflowControlError(w, err)
		return
	}
	common.ReplyOK(w, nil)
}
