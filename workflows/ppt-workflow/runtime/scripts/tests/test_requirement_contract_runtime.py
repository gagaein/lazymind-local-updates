from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_stage  # noqa: E402


def _requirement(
    requirement_id: str,
    raw_text: str,
    *,
    applies_to: list[str],
    scope: dict | None = None,
    priority: int = 400,
) -> dict:
    return {
        'id': requirement_id,
        'source': 'direct_user',
        'priority': priority,
        'strength': 'hard',
        'scope': scope or {'kind': 'deck'},
        'category': 'content',
        'raw_text': raw_text,
        'applies_to': applies_to,
    }


class RequirementContractRuntimeTest(unittest.TestCase):
    def test_style_and_outline_model_payloads_receive_the_same_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            deck = Path(temp)
            contract = {
                'version': 1,
                'precedence': ['direct_user', 'source_document', 'selected_choice'],
                'requirements': [
                    {
                        **_requirement(
                            'req_visual', '必须遵守自定义品牌留白规则',
                            applies_to=['style', 'outline', 'page', 'final'],
                        ),
                        'category': 'visual',
                    },
                ],
            }
            (deck / 'task_pack.json').write_text(json.dumps({
                'ppt_mode': 'fast', 'params': {'page_count': 1, 'language': 'zh-Hans'},
            }), encoding='utf-8')
            (deck / 'info_pack.json').write_text(json.dumps({
                'user_query': '制作一页演示',
                'query_normalized': {'topic': '测试'},
                'user_assets': {},
                'requirement_contract': contract,
            }), encoding='utf-8')
            captured: dict[str, dict] = {}

            def style_llm(_system: str, user: str, **_kwargs) -> str:
                captured['style'] = json.loads(user)
                return json.dumps({
                    'design_style': {'id': 1},
                    'color_tone': {'id': 1},
                    'primary_color': {'id': 1},
                    'palette': {'primary': '#111111'},
                    'typography': {'title': 'Arial'},
                })

            original_dimensions = run_stage._load_style_dimensions
            run_stage._load_style_dimensions = lambda: None
            try:
                code, _ = run_stage._capture_cmd(run_stage.cmd_style, deck, llm_call=style_llm)
            finally:
                run_stage._load_style_dimensions = original_dimensions
            self.assertEqual(code, 0)

            def outline_llm(_system: str, user: str, **_kwargs) -> str:
                captured['outline'] = json.loads(user)
                return json.dumps({'pages': [{'title': '第一页'}]})

            code, _ = run_stage._capture_cmd(run_stage.cmd_outline, deck, llm_call=outline_llm)
            self.assertEqual(code, 0)
            self.assertEqual(
                captured['style']['requirement_contract']['requirements'][0]['id'],
                'req_visual',
            )
            self.assertEqual(
                captured['outline']['requirement_contract']['requirements'][0]['id'],
                'req_visual',
            )

    def test_page_prompt_receives_global_and_matching_page_requirements(self) -> None:
        info_pack = {'requirement_contract': {
            'version': 1,
            'precedence': ['direct_user', 'source_document', 'selected_choice'],
            'requirements': [
                _requirement('req_global', '所有页面内容必须可编辑', applies_to=['page', 'final']),
                _requirement(
                    'req_page_9', '第 9 页使用深紫背景',
                    applies_to=['style', 'page', 'final'],
                    scope={'kind': 'page', 'page_no': 9},
                ),
                _requirement(
                    'req_page_8', '第 8 页使用照片',
                    applies_to=['page', 'final'],
                    scope={'kind': 'page', 'page_no': 8},
                ),
            ],
        }}

        payload = run_stage._requirement_payload(info_pack, 'page', page_no=9)
        prompt = run_stage._build_brief_page_query(
            '页面标题与正文', {'palette': {'primary': '#000000'}},
            requirement_contract=payload,
        )

        self.assertIn('req_global', prompt)
        self.assertIn('所有页面内容必须可编辑', prompt)
        self.assertIn('req_page_9', prompt)
        self.assertIn('第 9 页使用深紫背景', prompt)
        self.assertNotIn('req_page_8', prompt)
        self.assertIn('USER REQUIREMENT CONTRACT wins', prompt)

    def test_coverage_fails_if_any_responsible_stage_silently_drops_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            deck = Path(temp)
            contract = {
                'version': 1,
                'precedence': ['direct_user', 'source_document', 'selected_choice'],
                'requirements': [
                    _requirement(
                        'req_all', '遵守品牌规则',
                        applies_to=['style', 'outline', 'page', 'final'],
                    ),
                ],
            }
            info_pack = {'requirement_contract': contract}
            (deck / 'info_pack.json').write_text(json.dumps(info_pack), encoding='utf-8')
            (deck / 'task_pack.json').write_text(json.dumps({
                'params': {'page_count': 2},
            }), encoding='utf-8')

            run_stage._record_requirement_application(deck, info_pack, 'style', 'style_spec.json')
            run_stage._record_requirement_application(deck, info_pack, 'outline', 'outline.json')
            run_stage._record_requirement_application(
                deck, info_pack, 'page', 'pages/page_001.html', page_no=1,
            )
            missing = run_stage._validate_requirement_coverage(deck, info_pack, page_count=2)
            self.assertEqual(missing, [{'id': 'req_all', 'missing': ['page:2']}])

            run_stage._record_requirement_application(
                deck, info_pack, 'page', 'pages/page_002.html', page_no=2,
            )
            self.assertEqual(
                run_stage._validate_requirement_coverage(deck, info_pack, page_count=2),
                [],
            )


if __name__ == '__main__':
    unittest.main()
