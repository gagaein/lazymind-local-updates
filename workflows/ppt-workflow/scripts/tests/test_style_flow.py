from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


def _import_stubs() -> dict[str, types.ModuleType]:
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

    modules = {
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
    return modules


TOOLS_PATH = Path(__file__).resolve().parents[1] / 'tools.py'
SPEC = importlib.util.spec_from_file_location('ppt_style_flow_tools_test', TOOLS_PATH)
TOOLS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
with mock.patch.dict(sys.modules, _import_stubs()):
    SPEC.loader.exec_module(TOOLS)


class StyleFlowCombinationTest(unittest.TestCase):
    COMBINATIONS = (
        ('auto', False, 'fast'),
        ('auto', True, 'fast'),
        ('preview_choice', False, 'standard'),
        ('preview_choice', True, 'standard'),
    )

    def test_requirement_publisher_derives_all_control_markers(self) -> None:
        cases = (
            ('auto', 'enabled', False, {'skip_style_choices'}),
            ('auto', 'disabled', True, {
                'skip_style_choices', 'skip_background_images',
                'skip_material_collection',
            }),
            ('preview_choice', 'enabled', False, set()),
            ('preview_choice', 'disabled', False, {'skip_background_images'}),
        )
        for style, backgrounds, skip_materials, expected_markers in cases:
            with self.subTest(style=style, backgrounds=backgrounds), mock.patch.object(
                TOOLS, 'save_artifacts',
                side_effect=lambda artifacts: {
                    'status': 'ok', 'saved_count': len(artifacts),
                },
            ) as save_batch:
                result = TOOLS.ppt_publish_requirement_analysis(
                    requirement_analysis='完整需求分析',
                    style_flow=style,
                    generate_background_images=backgrounds,
                    skip_material_collection=skip_materials,
                )

            artifacts = save_batch.call_args.args[0]
            values = {item['key']: item['value'] for item in artifacts}
            self.assertEqual(values['requirement_analysis'], '完整需求分析')
            self.assertEqual(values['style_flow'], style)
            self.assertEqual(values['generate_background_images'], backgrounds)
            self.assertEqual(
                values['ppt_capability_requirements'],
                f'AI_BACKGROUND_IMAGES: {backgrounds}',
            )
            derived = set(values) - {
                'requirement_analysis', 'ppt_capability_requirements',
                'style_flow', 'generate_background_images',
            }
            self.assertEqual(derived, expected_markers)
            self.assertEqual(result['saved_artifacts'], list(values))

    def test_requirement_publisher_rejects_invalid_semantic_choices_before_write(self) -> None:
        invalid_cases = (
            {'requirement_analysis': ''},
            {'style_flow': 'standard'},
            {'style_flow': 'AUTO'},
            {'generate_background_images': 'false'},
            {'generate_background_images': 'Disabled'},
            {'skip_material_collection': 'false'},
        )
        base = {
            'requirement_analysis': '完整需求分析',
            'style_flow': 'auto',
            'generate_background_images': 'disabled',
            'skip_material_collection': False,
        }
        for override in invalid_cases:
            with self.subTest(override=override), mock.patch.object(
                TOOLS, 'save_artifacts',
            ) as save_batch, self.assertRaises(RuntimeError):
                TOOLS.ppt_publish_requirement_analysis(**{**base, **override})
            save_batch.assert_not_called()

    def test_requirement_publisher_surfaces_batch_publication_failure(self) -> None:
        with mock.patch.object(
            TOOLS, 'save_artifacts', return_value={'status': 'error'},
        ), self.assertRaisesRegex(
            RuntimeError, 'failed to publish PPT requirement analysis',
        ):
            TOOLS.ppt_publish_requirement_analysis(
                requirement_analysis='完整需求分析',
                style_flow='auto',
                generate_background_images='disabled',
                skip_material_collection=False,
            )

    def test_each_of_four_combinations_initializes_ten_times(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.object(TOOLS, '_conversation_root', return_value=root), mock.patch.object(
                TOOLS, '_attach_material_images_to_deck',
                return_value={'attached': 0, 'reference_images': []},
            ):
                for flow, backgrounds, expected_mode in self.COMBINATIONS:
                    for run in range(10):
                        result = TOOLS.ppt_init_deck(
                            user_query=f'{flow}-{backgrounds}-{run}',
                            page_count=2,
                            style_flow=flow,
                            # A conflicting legacy value must not own the branch.
                            ppt_mode='standard' if expected_mode == 'fast' else 'fast',
                            generate_background_images=backgrounds,
                        )
                        deck = Path(result['deck_dir'])
                        pack = json.loads((deck / 'task_pack.json').read_text(encoding='utf-8'))
                        self.assertEqual(result['style_flow'], flow)
                        self.assertEqual(result['ppt_mode'], expected_mode)
                        self.assertEqual(pack['params']['style_flow'], flow)
                        self.assertEqual(pack['ppt_mode'], expected_mode)
                        self.assertIs(
                            pack['params']['generate_background_images'], backgrounds,
                        )

    @staticmethod
    def _prepared_deck(root: Path, flow: str, backgrounds: bool, run: int) -> Path:
        deck = root / f'{flow}-{backgrounds}-{run}'
        deck.mkdir()
        (deck / 'task_pack.json').write_text(json.dumps({
            'deck_id': deck.name,
            'ppt_mode': 'standard' if flow == 'preview_choice' else 'fast',
            'params': {
                'page_count': 2,
                'style_flow': flow,
                'generate_background_images': backgrounds,
            },
        }), encoding='utf-8')
        (deck / 'info_pack.json').write_text(json.dumps({
            'user_query': '两页测试 PPT', 'user_assets': {},
        }), encoding='utf-8')
        if flow == 'preview_choice':
            (deck / 'style_samples.json').write_text(json.dumps({
                'samples': [
                    {'sample_id': sample, 'style_spec': {}}
                    for sample in ('A', 'B', 'C')
                ],
            }), encoding='utf-8')
        return deck

    def test_each_of_four_combinations_builds_outline_ten_times(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for flow, backgrounds, _expected_mode in self.COMBINATIONS:
                for run in range(10):
                    deck = self._prepared_deck(root, flow, backgrounds, run)
                    stage_calls: list[tuple[str, str | None]] = []

                    def run_stage(deck_dir: str, *, stage: str, sample=None, **_kwargs):
                        stage_calls.append((stage, sample))
                        if stage == 'style':
                            style = {
                                'design_style': {'id': 1},
                                'color_tone': {'id': 1},
                                'primary_color': {'id': 1},
                                'palette': {'primary': '#1976D2'},
                            }
                            if sample:
                                style['_selected_sample'] = {'sample_id': sample}
                            (Path(deck_dir) / 'style_spec.json').write_text(
                                json.dumps(style), encoding='utf-8',
                            )
                        if stage == 'content-outline':
                            (Path(deck_dir) / 'outline.json').write_text(
                                json.dumps({'pages': [
                                    {'page_no': 1, 'title': '第一页'},
                                    {'page_no': 2, 'title': '第二页'},
                                ]}),
                                encoding='utf-8',
                            )
                        return {'status': 'ok', 'pages': 2}

                    with mock.patch.object(
                        TOOLS, '_resolve_deck_dir', return_value=deck,
                    ), mock.patch.object(
                        TOOLS, '_attach_material_images_to_deck',
                        return_value={'attached': 0, 'reference_images': []},
                    ), mock.patch.object(
                        TOOLS, 'ppt_run_stage', side_effect=run_stage,
                    ), mock.patch.object(
                        TOOLS, '_publish_deck_outline',
                        return_value={'ok': True, 'page_count': 2, 'chars': 80},
                    ):
                        result = TOOLS.ppt_build_outline(
                            user_query='两页测试 PPT', page_count=2,
                            deck_dir=str(deck), style_flow=flow,
                            style_selection='B' if flow == 'preview_choice' else None,
                            generate_background_images=backgrounds,
                        )

                    self.assertEqual(result['style_flow'], flow)
                    self.assertIs(result['background_images_enabled'], backgrounds)
                    self.assertEqual(
                        stage_calls,
                        [
                            ('preflight', None),
                            ('style', 'B' if flow == 'preview_choice' else None),
                            ('preflight', None),
                            ('content-outline', None),
                        ],
                    )

    def test_legacy_standard_without_samples_recovers_as_auto(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            deck = Path(temp)
            (deck / 'task_pack.json').write_text(json.dumps({
                'ppt_mode': 'standard', 'params': {'page_count': 1},
            }), encoding='utf-8')

            pack, flow = TOOLS._persist_deck_style_flow(deck)

            self.assertEqual(flow, 'auto')
            self.assertEqual(pack['ppt_mode'], 'fast')
            self.assertEqual(pack['params']['style_flow'], 'auto')

    def test_explicit_background_choice_overrides_prepared_deck_both_ways(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cases = ((True, False), (False, True))
            for index, (stored, requested) in enumerate(cases):
                deck = self._prepared_deck(root, 'auto', stored, index)

                def run_stage(deck_dir: str, *, stage: str, **_kwargs):
                    if stage == 'style':
                        (Path(deck_dir) / 'style_spec.json').write_text(
                            json.dumps({
                                'design_style': {'id': 1},
                                'color_tone': {'id': 1},
                                'primary_color': {'id': 1},
                                'palette': {'primary': '#1976D2'},
                            }),
                            encoding='utf-8',
                        )
                    if stage == 'content-outline':
                        (Path(deck_dir) / 'outline.json').write_text(
                            json.dumps({'pages': [
                                {'page_no': 1, 'title': '第一页'},
                                {'page_no': 2, 'title': '第二页'},
                            ]}),
                            encoding='utf-8',
                        )
                    return {'status': 'ok'}

                with mock.patch.object(
                    TOOLS, '_resolve_deck_dir', return_value=deck,
                ), mock.patch.object(
                    TOOLS, '_attach_material_images_to_deck',
                    return_value={'attached': 0, 'reference_images': []},
                ), mock.patch.object(
                    TOOLS, 'ppt_run_stage', side_effect=run_stage,
                ), mock.patch.object(
                    TOOLS, '_publish_deck_outline',
                    return_value={'ok': True, 'page_count': 2, 'chars': 80},
                ):
                    result = TOOLS.ppt_build_outline(
                        user_query='两页测试 PPT', deck_dir=str(deck),
                        style_flow='auto',
                        generate_background_images=requested,
                    )

                pack = json.loads(
                    (deck / 'task_pack.json').read_text(encoding='utf-8')
                )
                self.assertIs(result['background_images_enabled'], requested)
                self.assertIs(
                    pack['params']['generate_background_images'], requested,
                )

    def test_capability_gate_accepts_all_four_independent_combinations(self) -> None:
        for flow, backgrounds, _mode in self.COMBINATIONS:
            marker = (
                'AI_BACKGROUND_IMAGES: enabled'
                if backgrounds else 'AI_BACKGROUND_IMAGES: disabled'
            )
            result = TOOLS.check_ppt_workflow_capabilities(
                marker,
                style_flow=flow,
                generate_background_images='enabled' if backgrounds else 'disabled',
            )
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(result['style_flow'], flow)


class SourceBundleTest(unittest.TestCase):
    def test_requirement_scan_does_not_relabel_the_whole_body_when_no_requirement_exists(self) -> None:
        blocks = [
            {'block_id': 'b1', 'type': 'heading1', 'text': '行业背景'},
            {'block_id': 'b2', 'type': 'paragraph', 'text': '市场正在稳定增长。'},
            {'block_id': 'b3', 'type': 'paragraph', 'text': '这是对市场现状的补充说明。'},
        ]

        contract = TOOLS._presentation_contract(blocks, 'hash', title='研究材料')

        self.assertFalse(contract['scan_coverage']['explicit_requirements_found'])
        self.assertTrue(contract['scan_coverage']['all_blocks_scanned'])
        self.assertEqual(contract['requirements'], [])
        self.assertEqual(contract['concept']['title'], '研究材料')
        self.assertTrue(contract['concept']['blocks'])

    def test_requirement_scan_keeps_all_bullets_under_a_requirement_heading(self) -> None:
        blocks = [
            {'block_id': 'b1', 'type': 'heading2', 'text': 'PPT 制作要求'},
            *[
                {'block_id': f'b{index}', 'type': 'bullet', 'text': f'制作项 {index}'}
                for index in range(2, 17)
            ],
            {'block_id': 'b17', 'type': 'heading2', 'text': '业务正文'},
        ]

        contract = TOOLS._presentation_contract(blocks, 'hash')

        self.assertTrue(contract['scan_coverage']['explicit_requirements_found'])
        self.assertEqual(
            [item['block_id'] for item in contract['requirements']],
            [f'b{index}' for index in range(1, 17)],
        )

    def test_prepare_source_fetches_once_and_does_not_download_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            calls = {'load': 0}
            payload = {
                'source_document': {
                    'document_id': 'local-doc', 'revision': 'rev-3', 'title': '项目材料',
                    'stage': 'final',
                    'provider_binding': {
                        'provider': 'feishu', 'document_id': 'remote-doc',
                        'uri': 'https://example.test/doc/1',
                    },
                    'blocks': [
                        {
                            'node_id': 'h1', 'type': 'heading1', 'content': 'PPT 要求',
                            'provider_binding': {'block_id': 'remote-h1'}, 'children': [],
                        },
                        {
                            'node_id': 'p1', 'type': 'paragraph', 'content': '必须做成 6 页',
                            'provider_binding': {'block_id': 'remote-p1'}, 'children': [],
                        },
                        {
                            'node_id': 'i1', 'type': 'image', 'content': '产品图',
                            'provider_binding': {'block_id': 'remote-i1'},
                            'provider_payload': {'raw_block': {'image': {'token': 'secret-token'}}},
                            'children': [],
                        },
                    ],
                },
                'target_document': {'doc_id': 'remote-doc', 'title': '项目材料'},
                'input_resources': [],
                'resource_warnings': [],
            }

            class ResourceToolkit:
                def load_document(self, **_kwargs):
                    calls['load'] += 1
                    return json.dumps(payload, ensure_ascii=False)

            document_tools = types.ModuleType('lazymind.document_tools')
            document_tools.WriterResourceToolkit = ResourceToolkit
            resources = types.ModuleType('lazymind.document_tools.resources')
            resources.find_provider_locator = lambda _value: 'https://example.test/doc/1'
            context = SimpleNamespace(params={
                'launch_user_input': '请基于 https://example.test/doc/1 制作 PPT',
            })
            with mock.patch.dict(sys.modules, {
                'lazymind.document_tools': document_tools,
                'lazymind.document_tools.resources': resources,
            }), mock.patch.object(
                TOOLS, 'require_context', return_value=context,
            ), mock.patch.object(
                TOOLS, '_conversation_root', return_value=root,
            ), mock.patch.object(
                TOOLS, '_save_artifact', return_value={'status': 'ok'},
            ):
                result = TOOLS.ppt_prepare_source_document()

            bundle = json.loads(Path(result['bundle_path']).read_text(encoding='utf-8'))

        self.assertEqual(calls['load'], 1)
        self.assertEqual(result['image_bytes_downloaded'], 0)
        self.assertTrue(result['requirement_scan']['coverage']['all_blocks_scanned'])
        self.assertEqual(bundle['source_image_count'], 1)
        self.assertEqual(len(bundle['_media_snapshot']['source_document']['blocks']), 1)
        self.assertEqual(bundle['asset_manifest'], [])

    def test_deep_reader_pages_the_frozen_body_to_eof_and_publishes_receipt(self) -> None:
        bundle = {
            'source_url': 'https://example.test/doc/1', 'version': 'rev-4',
            'text_sha256': 'sha',
            'ordered_blocks': [
                {'block_id': f'b{index}', 'type': 'paragraph', 'text': str(index) * 800}
                for index in range(3)
            ],
            'presentation_contract': {'requirements': []},
        }
        context = SimpleNamespace(params={'remote_inputs': {'source_bundle': bundle}})
        saved: list[dict] = []
        start = 0
        seen: list[int] = []
        with mock.patch.object(
            TOOLS, 'require_context', return_value=context,
        ), mock.patch.object(
            TOOLS, '_save_artifact',
            side_effect=lambda **kwargs: saved.append(kwargs) or {'status': 'ok'},
        ):
            while True:
                result = TOOLS.ppt_read_source_document(start_index=start, max_chars=1000)
                seen.extend(item['index'] for item in result['blocks'])
                if result['eof']:
                    break
                start = result['next_index']

        self.assertEqual(seen, [0, 1, 2])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['key'], 'source_read_complete')
        self.assertTrue(saved[0]['value']['complete'])

    def test_source_images_use_frozen_tickets_without_refetching_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_image = root / 'source.png'
            source_image.write_bytes(b'image')
            bundle = {
                'source_url': 'https://example.test/doc/1',
                'version': 'rev-5', 'source_image_count': 1,
                '_media_snapshot': {
                    'source_document': {
                        'document_id': 'doc', 'stage': 'final',
                        'provider_binding': {'provider': 'feishu'},
                        'blocks': [{'node_id': 'i1', 'type': 'image'}],
                    },
                    'input_resources': [],
                },
            }
            context = SimpleNamespace(params={
                'session_id': 'session-1',
                'remote_inputs': {'source_bundle': bundle},
            })
            collect = mock.Mock(return_value={
                'media_assets': {'assets': {'img-1': {
                    'local_path': str(source_image), 'caption': '产品图',
                    'meta': {'content_ref': {'node_id': 'i1'}},
                }}},
                'warnings': [],
            })
            writing = types.ModuleType('lazymind.document_tools.writing')
            writing.collect_document_media = collect
            with mock.patch.dict(sys.modules, {
                'lazymind.document_tools.writing': writing,
            }), mock.patch.object(
                TOOLS, 'require_context', return_value=context,
            ), mock.patch.object(
                TOOLS, '_conversation_root', return_value=root,
            ), mock.patch.object(
                TOOLS, '_register_source_material_images',
                return_value={'registered': 1, 'total': 1},
            ) as register:
                result = TOOLS.ppt_materialize_source_images()

        self.assertFalse(result['provider_document_refetched'])
        self.assertFalse(result['image_analysis_performed'])
        self.assertEqual(collect.call_count, 1)
        self.assertEqual(
            collect.call_args.kwargs['source_document'],
            bundle['_media_snapshot']['source_document'],
        )
        register.assert_called_once()

    def test_planning_context_reads_bound_revision_and_keeps_source_anchors(self) -> None:
        bundle = {
            'title': '源文档',
            'source_url': 'https://example.test/doc/1',
            'version': 'rev-1',
            'presentation_contract': {'source_is_authoritative': True},
            'ordered_blocks': [
                {'block_id': 'b1', 'source_block_id': 'remote-1', 'text': '必须使用素材图'},
            ],
            'asset_manifest': [{
                'asset_id': 'img-1', 'order': 1, 'caption': '架构图',
                'source_block_id': 'remote-1', 'required': True,
                'reuse_allowed': True,
            }],
        }
        context = SimpleNamespace(params={'remote_inputs': {
            'requirement_analysis': '五页技术汇报',
            'material_summary': '已有一张架构图',
            'source_bundle': bundle,
        }})
        with mock.patch.object(TOOLS, 'require_context', return_value=context):
            result = TOOLS.ppt_get_planning_context()

        self.assertEqual(result['requirement_analysis'], '五页技术汇报')
        self.assertEqual(result['source_document']['version'], 'rev-1')
        self.assertIn('[remote-1] 必须使用素材图', result['source_document']['source_excerpt'])
        self.assertTrue(result['source_document']['asset_manifest'][0]['required'])

    def test_deck_copies_bound_source_bundle_and_keeps_exact_revision(self) -> None:
        bundle = {
            'provider': 'feishu', 'document_id': 'doc-1', 'title': '方案',
            'source_url': 'https://example.test/doc/1', 'version': 'rev-7',
            'text_sha256': 'abc',
            'ordered_blocks': [{'block_id': 'b1', 'text': '完整要求'}],
            'presentation_contract': {'requirements': [{'block_id': 'b1', 'text': '完整要求'}]},
            'asset_manifest': [],
        }
        context = SimpleNamespace(params={'remote_inputs': {'source_bundle': bundle}})
        with tempfile.TemporaryDirectory() as temp:
            deck = Path(temp)
            (deck / 'info_pack.json').write_text(json.dumps({
                'user_assets': {'reference_docs': [], 'reference_docs_failed': []},
                'document_digest': None,
            }), encoding='utf-8')
            with mock.patch.object(TOOLS, 'require_context', return_value=context):
                result = TOOLS._attach_source_bundle_to_deck(deck)

            info = json.loads((deck / 'info_pack.json').read_text(encoding='utf-8'))
            copied = json.loads((deck / 'source_bundle.json').read_text(encoding='utf-8'))
            raw = json.loads((deck / 'source_documents.json').read_text(encoding='utf-8'))
        self.assertTrue(result['attached'])
        self.assertEqual(info['source_bundle']['version'], 'rev-7')
        self.assertEqual(copied['version'], 'rev-7')
        self.assertNotIn('_media_snapshot', copied)
        self.assertEqual(raw['documents'][0]['text'], '完整要求')

    def test_source_images_bypass_optional_cap_but_optional_images_remain_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            deck = root / 'deck'
            deck.mkdir()
            (deck / 'info_pack.json').write_text(json.dumps({
                'source_bundle': {'version': 'rev-1'},
                'user_assets': {'reference_images': []},
            }), encoding='utf-8')
            images = []
            for index in range(15):
                path = root / f'optional-{index}.png'
                path.write_bytes(b'optional')
                images.append({'path': str(path), 'source': 'web'})
            for index in range(3):
                path = root / f'source-{index}.png'
                path.write_bytes(b'source')
                images.append({
                    'path': str(path), 'source_type': 'source_document',
                    'source_version': 'rev-1', 'asset_id': f'asset-{index}',
                    'required': True, 'reuse_allowed': True,
                })
            with mock.patch.object(
                TOOLS, '_load_material_manifest', return_value={'images': images},
            ):
                attached = TOOLS._attach_material_images_to_deck(deck)

            info = json.loads((deck / 'info_pack.json').read_text(encoding='utf-8'))
        self.assertEqual(attached['attached'], 15)
        metadata = info['user_assets']['reference_image_metadata']
        self.assertEqual(sum(item['required'] for item in metadata.values()), 3)

    def test_importer_publishes_ordered_blocks_and_all_source_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_image = root / 'provider-image.png'
            source_image.write_bytes(b'provider-image')
            payload = {
                'source_document': {
                    'document_id': 'local-doc', 'revision': 'rev-2', 'title': '设计要求',
                    'provider_binding': {'provider': 'feishu', 'document_id': 'remote-doc'},
                    'blocks': [{
                        'node_id': 'b1', 'type': 'paragraph', 'content': '必须保留架构图',
                        'provider_binding': {'block_id': 'remote-b1'}, 'children': [],
                    }],
                },
                'target_document': {'doc_id': 'remote-doc', 'title': '设计要求'},
                'input_resources': [{
                    'resource_id': 'img-1', 'resource_type': 'image',
                    'uri': str(source_image),
                }],
                'resource_warnings': [],
            }

            class ResourceToolkit:
                def load_document(self, **_kwargs):
                    return json.dumps(payload, ensure_ascii=False)

            document_tools = types.ModuleType('lazymind.document_tools')
            document_tools.WriterResourceToolkit = ResourceToolkit
            resources = types.ModuleType('lazymind.document_tools.resources')
            resources.find_provider_locator = lambda _value: 'https://example.test/doc/1'
            writing = types.ModuleType('lazymind.document_tools.writing')
            writing.collect_document_media = lambda *_args, **_kwargs: {
                'media_assets': {'assets': {'img-1': {
                    'local_path': str(source_image), 'caption': '架构图',
                    'meta': {'content_ref': {'node_id': 'b1'}},
                }}},
                'warnings': [],
            }
            context = SimpleNamespace(params={
                'user_input': '请基于 https://example.test/doc/1 制作 PPT',
                'session_id': 'session-1',
            })
            with mock.patch.dict(sys.modules, {
                'lazymind.document_tools': document_tools,
                'lazymind.document_tools.resources': resources,
                'lazymind.document_tools.writing': writing,
            }), mock.patch.object(
                TOOLS, 'require_context', return_value=context,
            ), mock.patch.object(
                TOOLS, '_conversation_root', return_value=root,
            ), mock.patch.object(
                TOOLS, '_save_artifact', return_value={'status': 'ok'},
            ), mock.patch.object(
                TOOLS, 'save_artifacts',
                side_effect=lambda artifacts: {'status': 'ok', 'saved_count': len(artifacts)},
            ):
                result = TOOLS.ppt_import_source_document()

            bundle = json.loads(Path(result['bundle_path']).read_text(encoding='utf-8'))
            manifest = json.loads((root / 'material_images' / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(bundle['version'], 'rev-2')
        self.assertEqual(bundle['ordered_blocks'][0]['source_block_id'], 'remote-b1')
        self.assertEqual(bundle['asset_manifest'][0]['asset_id'], 'img-1')
        self.assertTrue(manifest['images'][0]['required'])


if __name__ == '__main__':
    unittest.main()
