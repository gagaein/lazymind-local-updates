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


if __name__ == '__main__':
    unittest.main()
