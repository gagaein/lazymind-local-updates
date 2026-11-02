package main

import (
	"path/filepath"
	"testing"
)

func TestProcessTextMatchesDesktopResourceRoot(t *testing.T) {
	root := t.TempDir()
	paths := RuntimePaths{
		RepoRoot:      filepath.Join(root, "LazyMind.app", "Contents", "Resources", "runtime", "app"),
		BuildRoot:     filepath.Join(root, "LazyMind.app", "Contents", "Resources", "runtime"),
		ResourcesRoot: filepath.Join(root, "LazyMind.app", "Contents", "Resources", "runtime"),
		RuntimeRoot:   filepath.Join(root, "Library", "Application Support", "LazyMind"),
	}
	caddy := filepath.Join(paths.ResourcesRoot, "bin", "caddy")
	if !processTextMatchesRuntime(paths, caddy) {
		t.Fatalf("desktop resource binary should match runtime: %s", caddy)
	}
}

func TestProcessTextMatchesLocalBuildRoot(t *testing.T) {
	root := t.TempDir()
	paths := RuntimePaths{
		RepoRoot:    filepath.Join(root, "LazyMind"),
		BuildRoot:   filepath.Join(root, "LazyMind", "local", "build"),
		RuntimeRoot: filepath.Join(root, "Library", "Application Support", "LazyMind"),
	}
	manager := filepath.Join(paths.BuildRoot, "bin", "local-runtime-manager")
	if !processTextMatchesRuntime(paths, manager) {
		t.Fatalf("local build binary should match runtime: %s", manager)
	}
}

func TestProcessTextMatchesRuntimePreservesAgentConnectors(t *testing.T) {
	root := t.TempDir()
	paths := RuntimePaths{
		RepoRoot:      filepath.Join(root, "LazyMind"),
		BuildRoot:     filepath.Join(root, "LazyMind", "local", "build"),
		ResourcesRoot: filepath.Join(root, "LazyMind.app", "Contents", "Resources", "runtime"),
		RuntimeRoot:   filepath.Join(root, "Library", "Application Support", "LazyMind"),
	}
	connector := filepath.Join(paths.BuildRoot, "bin", "lazymind")
	tests := []struct {
		name       string
		executable string
		command    string
	}{
		{name: "MCP proxy", executable: connector, command: connector + " mcp proxy"},
		{name: "Assistant Bridge", executable: connector, command: connector + " assistant serve"},
		{name: "desktop connector", executable: filepath.Join(paths.ResourcesRoot, "bin", "lazymind")},
		{name: "Windows connector", executable: filepath.Join(paths.BuildRoot, "bin", "LazyMind.EXE")},
		{name: "replaced Linux connector", executable: connector + " (deleted)", command: connector + " mcp proxy"},
		{name: "runtime connector", executable: filepath.Join(paths.RuntimeRoot, "bin", "lazymind")},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if processTextMatchesRuntime(paths, test.executable, test.command) {
				t.Fatalf("independently managed connector must not be cleaned up: %s", test.executable)
			}
		})
	}

	// A connector mentioned as an argument must not hide an actual runtime process.
	for _, executable := range []string{
		filepath.Join(paths.BuildRoot, "bin", "local-runtime-manager"),
		filepath.Join(paths.BuildRoot, "bin", "core"),
		filepath.Join(paths.ResourcesRoot, "bin", "caddy"),
		filepath.Join(paths.BuildRoot, "deps", "python", "algorithm", "bin", "python"),
	} {
		if !processTextMatchesRuntime(paths, executable, "--connector "+connector) {
			t.Fatalf("runtime process must remain eligible for cleanup: %s", executable)
		}
	}
}

func TestIsRuntimeGuardCommandOnlyMatchesGuardInvocation(t *testing.T) {
	manager := "/tmp/LazyMind/local/build/bin/local-runtime-manager"
	if !isRuntimeGuardCommand(manager, []string{"guard", "--owner-pid", "123"}) {
		t.Fatal("guard invocation should be excluded from stale-process scanning")
	}
	if isRuntimeGuardCommand(manager, []string{"up"}) {
		t.Fatal("runtime manager up process must remain scannable")
	}
	if isRuntimeGuardCommand("/tmp/LazyMind/local/build/bin/other-manager", []string{"guard"}) {
		t.Fatal("other executables must not be treated as the runtime guard")
	}
}
