from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


def _import_stubs() -> dict[str, types.ModuleType]:
    requests = types.ModuleType('requests')
    requests.get = lambda *args, **kwargs: None
    requests.post = lambda *args, **kwargs: None
    lazyllm = types.ModuleType('lazyllm')
    lazyllm.ThreadPoolExecutor = concurrent.futures.ThreadPoolExecutor
    lazyllm_tools = types.ModuleType('lazyllm.tools')
    lazyllm_agent = types.ModuleType('lazyllm.tools.agent')
    lazyllm_agent.ToolExecutionError = RuntimeError
    lazyllm.tools = lazyllm_tools
    lazyllm_tools.agent = lazyllm_agent

    context = types.ModuleType('lazymind.chat.engine.subagent.context')
    context.require_context = lambda: None
    subagent_tools = types.ModuleType('lazymind.chat.engine.subagent.tools')
    subagent_tools._resolve_artifact_text = lambda value: str(value or '')
    subagent_tools._save_artifact = lambda **kwargs: {'ok': True, **kwargs}
    subagent_tools.save_artifacts = lambda artifacts: {
        'status': 'ok', 'saved_count': len(artifacts), 'artifacts': artifacts,
    }
    subagent_tools._workflow_client = lambda: None
    multimodal = types.ModuleType('lazymind.chat.engine.tools.multimodal')
    multimodal.image_generator = lambda *args, **kwargs: None
    static_file = types.ModuleType('lazymind.chat.service.utils.static_file_url')
    static_file._upload_root = lambda: Path(tempfile.gettempdir())
    static_file.file_relative_path = lambda value: value
    static_file.encode_static_file_path = lambda value: value
    static_file.local_path_from_static_file_url = lambda value: value
    model_config = types.ModuleType('lazymind.model_config')
    model_config.is_model_role_available = lambda _role: True

    return {
        'requests': requests,
        'lazyllm': lazyllm,
        'lazyllm.tools': lazyllm_tools,
        'lazyllm.tools.agent': lazyllm_agent,
        'lazymind': types.ModuleType('lazymind'),
        'lazymind.chat': types.ModuleType('lazymind.chat'),
        'lazymind.chat.engine': types.ModuleType('lazymind.chat.engine'),
        'lazymind.chat.engine.subagent': types.ModuleType('lazymind.chat.engine.subagent'),
        'lazymind.chat.engine.subagent.context': context,
        'lazymind.chat.engine.subagent.tools': subagent_tools,
        'lazymind.chat.engine.tools': types.ModuleType('lazymind.chat.engine.tools'),
        'lazymind.chat.engine.tools.multimodal': multimodal,
        'lazymind.chat.service': types.ModuleType('lazymind.chat.service'),
        'lazymind.chat.service.utils': types.ModuleType('lazymind.chat.service.utils'),
        'lazymind.chat.service.utils.static_file_url': static_file,
        'lazymind.model_config': model_config,
    }


TOOLS_PATH = Path(__file__).resolve().parents[1] / 'tools.py'
SPEC = importlib.util.spec_from_file_location('ppt_requirement_contract_tools_test', TOOLS_PATH)
TOOLS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
with mock.patch.dict(sys.modules, _import_stubs()):
    SPEC.loader.exec_module(TOOLS)


class RequirementContractTest(unittest.TestCase):
    def test_structured_source_requirements_survive_with_scope_and_exact_values(self) -> None:
        task_pack = {'params': {'page_count': 9}}
        info_pack = {
            'original_user_query': '标题字号为 30-36 pt；制作 9 页中文 PPT。',
        }
        source_requirements = TOOLS._source_requirements_payload([
            {
                'text': '标题 30–36pt',
                'source_ref': 'brief.docx:typography',
                'scope': {'kind': 'deck'},
                'category': 'visual',
                'strength': 'hard',
            },
            {
                'text': '正文字号 30–36pt',
                'source_ref': 'brief.docx:body-typography',
                'scope': {'kind': 'deck'},
                'category': 'visual',
                'strength': 'hard',
            },
            {
                'text': '主色必须使用 #3A2A78，辅色使用 #F2C14E',
                'source_ref': 'brief.docx:palette',
                'scope': {'kind': 'deck'},
                'category': 'visual',
                'strength': 'hard',
            },
            {
                'text': 'P9 使用深紫背景',
                'source_ref': 'brief.docx:p9',
                'scope': {'kind': 'page', 'page_no': 9},
                'category': 'visual',
                'strength': 'hard',
            },
        ])

        contract = TOOLS._build_requirement_contract(
            task_pack, info_pack, source_requirements=source_requirements,
        )

        exact_title = [
            item for item in contract['requirements']
            if '标题' in item['raw_text'] and '30' in item['raw_text']
            and '36' in item['raw_text']
        ]
        self.assertEqual(len(exact_title), 2)
        self.assertEqual(
            [item['source'] for item in exact_title],
            ['direct_user', 'source_document'],
        )
        self.assertTrue(any(
            item['raw_text'] == '正文字号 30–36pt'
            for item in contract['requirements']
        ))
        palette = next(
            item for item in contract['requirements']
            if '#3A2A78' in item['raw_text']
        )
        self.assertEqual(palette['source_ref'], 'brief.docx:palette')
        page_nine = next(
            item for item in contract['requirements']
            if item['raw_text'] == 'P9 使用深紫背景'
        )
        self.assertEqual(page_nine['scope'], {'kind': 'page', 'page_no': 9})
        self.assertEqual(
            contract['source_requirements_sha256'], source_requirements['sha256'],
        )

    def test_material_publisher_saves_summary_and_source_requirements_atomically(self) -> None:
        bundle = {
            'presentation_contract': {
                'requirements': [{
                    'text': '正文 18–22pt',
                    'source_block_id': 'doc-block-7',
                }],
            },
        }
        captured: list[list[dict]] = []

        def save(artifacts: list[dict]) -> dict:
            captured.append(artifacts)
            return {'status': 'ok', 'saved_count': len(artifacts)}

        with mock.patch.object(
            TOOLS, '_workflow_input_value',
            side_effect=lambda slot: bundle if slot == 'source_bundle' else None,
        ), mock.patch.object(TOOLS, 'save_artifacts', side_effect=save):
            result = TOOLS.ppt_publish_material_summary(
                '材料摘要',
                [{
                    'text': '左右边距约 6%',
                    'source_ref': 'upload.pdf:p2',
                    'scope': {'kind': 'deck'},
                }],
            )

        self.assertEqual(result['saved_artifacts'], [
            'material_summary', 'source_requirements',
        ])
        self.assertEqual(len(captured), 1)
        self.assertEqual([item['key'] for item in captured[0]], [
            'material_summary', 'source_requirements',
        ])
        payload = captured[0][1]['value']
        self.assertEqual(
            [item['text'] for item in payload['requirements']],
            ['正文 18–22pt', '左右边距约 6%'],
        )

    def test_only_the_same_transport_occurrence_is_not_injected_twice(self) -> None:
        bundle = {
            'presentation_contract': {
                'requirements': [{
                    'text': '正文 18–22pt',
                    'source_block_id': 'doc-block-7',
                }],
            },
        }
        captured: list[list[dict]] = []

        with mock.patch.object(
            TOOLS, '_workflow_input_value',
            side_effect=lambda slot: bundle if slot == 'source_bundle' else None,
        ), mock.patch.object(
            TOOLS, 'save_artifacts',
            side_effect=lambda artifacts: captured.append(artifacts) or {
                'status': 'ok', 'saved_count': len(artifacts),
            },
        ):
            TOOLS.ppt_publish_material_summary('材料摘要', [
                {
                    'text': '正文 18–22pt',
                    'source_ref': 'doc-block-7',
                },
                {
                    'text': '正文 18–22pt',
                    'source_ref': 'upload.pdf:p3',
                },
            ])

        requirements = captured[0][1]['value']['requirements']
        self.assertEqual(
            [item['source_ref'] for item in requirements],
            ['doc-block-7', 'upload.pdf:p3'],
        )

    def test_contract_preserves_unknown_user_requirements_and_source_provenance(self) -> None:
        task_pack = {
            'params': {
                'page_count': 9,
                'generate_background_images': False,
                'style_hint': '克制、研究报告感',
            },
        }
        info_pack = {
            'original_user_query': (
                '制作 9 页中文 PPT；第 9 页使用深紫背景；所有内容必须可编辑。'
                '每页图片不得重复，并遵守我自定义的品牌留白规则。'
            ),
            'document_digest': {
                'presentation_contract': {
                    'source_is_authoritative': True,
                    'requirements': [{
                        'block_id': 'writer-8',
                        'source_block_id': 'doc-42',
                        'type': 'paragraph',
                        'text': '标题 30—32pt，正文 16—18pt，页边距 40px。',
                    }],
                },
            },
        }

        contract = TOOLS._build_requirement_contract(task_pack, info_pack)
        requirements = contract['requirements']
        raw_texts = [item['raw_text'] for item in requirements]

        self.assertTrue(any('品牌留白规则' in text for text in raw_texts))
        source = next(item for item in requirements if item['source'] == 'source_document')
        self.assertEqual(source['source_ref'], 'doc-42')
        self.assertEqual(source['priority'], 300)
        page_nine = next(item for item in requirements if '第 9 页' in item['raw_text'])
        self.assertEqual(page_nine['scope'], {'kind': 'page', 'page_no': 9})
        self.assertIn('page', page_nine['applies_to'])

        repeated = TOOLS._build_requirement_contract(task_pack, info_pack)
        self.assertEqual(
            [item['id'] for item in requirements],
            [item['id'] for item in repeated['requirements']],
        )

    def test_existing_contract_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            deck = Path(temp)
            (deck / 'task_pack.json').write_text(json.dumps({
                'params': {'page_count': 4, 'generate_background_images': False},
            }), encoding='utf-8')
            frozen = {'version': 1, 'requirements': [{'id': 'req_frozen'}]}
            (deck / 'info_pack.json').write_text(json.dumps({
                'original_user_query': '原始要求',
                'requirement_contract': frozen,
            }), encoding='utf-8')

            result = TOOLS._ensure_requirement_contract(deck)

            self.assertEqual(result, frozen)
            persisted = json.loads((deck / 'info_pack.json').read_text(encoding='utf-8'))
            self.assertEqual(persisted['requirement_contract'], frozen)

    def test_changed_source_requirements_cannot_silently_reuse_frozen_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            deck = Path(temp)
            (deck / 'task_pack.json').write_text(json.dumps({
                'params': {'page_count': 4},
            }), encoding='utf-8')
            (deck / 'info_pack.json').write_text(json.dumps({
                'requirement_contract': {
                    'version': 2,
                    'source_requirements_sha256': 'old-sha',
                    'requirements': [{'id': 'req_frozen'}],
                },
            }), encoding='utf-8')

            with mock.patch.object(
                TOOLS, '_workflow_input_value',
                side_effect=lambda slot: {
                    'version': 1,
                    'sha256': 'new-sha',
                    'requirements': [],
                } if slot == 'source_requirements' else None,
            ):
                with self.assertRaisesRegex(RuntimeError, 'requirement_contract_stale'):
                    TOOLS._ensure_requirement_contract(deck)

    def test_explicit_rebuild_refreshes_changed_source_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            deck = Path(temp)
            (deck / 'task_pack.json').write_text(json.dumps({
                'params': {'page_count': 4},
            }), encoding='utf-8')
            (deck / 'info_pack.json').write_text(json.dumps({
                'original_user_query': '制作 4 页 PPT',
                'requirement_contract': {
                    'version': 2,
                    'source_requirements_sha256': 'old-sha',
                    'requirements': [{'id': 'req_frozen'}],
                },
            }), encoding='utf-8')
            refreshed = TOOLS._source_requirements_payload([{
                'text': '正文 18–22pt',
                'source_ref': 'brief.docx:7',
                'scope': {'kind': 'deck'},
                'category': 'visual',
                'strength': 'hard',
            }])

            with mock.patch.object(
                TOOLS, '_workflow_input_value',
                side_effect=lambda slot: refreshed
                if slot == 'source_requirements' else None,
            ):
                result = TOOLS._ensure_requirement_contract(
                    deck, allow_source_refresh=True,
                )

            self.assertEqual(
                result['source_requirements_sha256'], refreshed['sha256'],
            )
            self.assertTrue(any(
                item['raw_text'] == '正文 18–22pt'
                for item in result['requirements']
            ))

    def test_requirement_summary_groups_global_and_page_scoped_rules(self) -> None:
        summary = TOOLS._format_requirement_contract_summary({
            'requirements': [
                {
                    'raw_text': '正文 18–22pt',
                    'scope': {'kind': 'deck'},
                    'source': 'source_document',
                    'source_ref': 'brief.docx:7',
                },
                {
                    'raw_text': 'P9 使用深紫背景',
                    'scope': {'kind': 'page', 'page_no': 9},
                    'source': 'direct_user',
                    'source_ref': 'user_query:2',
                },
            ],
        })

        self.assertIn('## 全局要求\n- 正文 18–22pt', summary)
        self.assertIn('## 第 9 页要求\n- P9 使用深紫背景', summary)
        self.assertIn('来源：源材料 · brief.docx:7', summary)
        self.assertIn('来源：用户输入 · user_query:2', summary)


if __name__ == '__main__':
    unittest.main()
