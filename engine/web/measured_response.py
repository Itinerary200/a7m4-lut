"""Pinned Hybrid grid response used by training, validation and rendering."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

SCHEMA = 'r5-measured-grid-response/1'
HYBRID_PRESET = 'r5-paired-20261107-nonlinear-he3'
HYBRID_SHA256 = '936af0b27f3c5f1ff422c20dd7c1436f92458407d1dd492a4edca2e5ef45e677'


def hybrid_response():
    return dict(schema=SCHEMA, preset=HYBRID_PRESET,
                sha256=HYBRID_SHA256, model='ILCE-7RM5')


def default_response():
    return hybrid_response()


def is_measured(value):
    return isinstance(value, dict) and value.get('schema') == SCHEMA

def require(value):
    if not is_measured(value):
        raise ValueError('请先导入 R5 实测网格响应标定 JSON；不能使用固定 3×3 矩阵替代实测模型')
    get(value)
    return value

def get(value):
    if not is_measured(value):
        raise ValueError('Unknown measured grid response schema')
    return _cached(json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')))

@lru_cache(maxsize=8)
def _cached(serialized):
    value = json.loads(serialized)
    if value.get('preset') == HYBRID_PRESET:
        if value!=hybrid_response():raise ValueError('R5 hybrid snapshot identity mismatch')
        raw=(__import__('pathlib').Path(__file__).resolve().parent/'data/r5/paired-20261107-nonlinear-he3.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=value['sha256']:raise ValueError('R5 hybrid model hash mismatch')
        from hybrid_response import HybridModel
        return HybridModel(json.loads(raw),value['sha256'],identity=value)
    raise ValueError('Only the pinned R5 Hybrid response is supported')


def _inference_ast(path, names=None):
    """Hash executable inference AST; fitting/regularizer edits are irrelevant.

    Imports are included, docstrings/comments are excluded. Explicit method and
    constant names keep a training-only change from invalidating a frozen grid.
    """
    import ast
    class WithoutDocstrings(ast.NodeTransformer):
        def generic_visit(self, node):
            node = super().generic_visit(node)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
                    node.body = node.body[1:]
            return node
    # 本地兼容守卫:上游用 locale 编码读自身源码;GBK locale 的 Windows 上
    # 读 UTF-8 中文注释会炸。这里固定用 utf-8 读源码文本。
    tree = WithoutDocstrings().visit(ast.parse(path.read_text(encoding="utf-8")))
    if names is None:
        selected = tree.body
    else:
        selected = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        by_name = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                by_name[node.name] = node
                if isinstance(node, ast.ClassDef):
                    for method in node.body:
                        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            by_name[node.name + '.' + method.name] = method
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name): by_name[target.id] = node
        for name in names:
            if name not in by_name: raise ValueError('Missing response inference source: ' + name)
            selected.append(by_name[name])
    value = ast.dump(ast.Module(body=selected, type_ignores=[]), include_attributes=False)
    return hashlib.sha256(value.encode()).hexdigest()


def inference_sources(response):
    """Exact response paths used by CPU, Metal, preview and signed-byte export."""
    get(response)  # Includes model JSON SHA and full pinned identity validation.
    here = Path(__file__).resolve().parent
    common = {
        'measured_response.py': ('is_measured', 'require', 'get', '_cached'),
        'paired_coordinates.py': None,
        '../scripts/residual_grid.py': ('SHAPE', 'NODES', 'stencil', 'coefficients', 'pack', 'unpack'),
        'gpu_tensor.py': ('TensorTools.__init__', 'TensorTools.tensor', 'stencil_tensor'),
    }
    common.update({
        'paired_response.py': ('_DETAIL_INDICES', '_c1_basis', '_c1_basis_tensor',
            'PairedModel.__init__', 'PairedModel.coordinates', 'PairedModel.stencil',
            'PairedModel.response', 'PairedModel.coordinates_tensor', 'PairedModel.response_tensor',
            'PairedModel.predict', 'PairedModel.predict_cpu'),
        'hybrid_response.py': None,
        'gpu_color.py': ('paired_tensor', 'paired_numpy'),
    })
    return {name: _inference_ast(here / name, names) for name, names in sorted(common.items())}


def runtime_fingerprint(response):
    manifest = dict(schema='r5-grid-response-inference/1', response=response,
                    sources=inference_sources(response))
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def verify_saved_runtime(identity):
    """Require the exact Hybrid identity and its complete inference runtime."""
    response = identity['response']
    if response != hybrid_response():
        raise ValueError('当前工作台只接受 R5 Hybrid 响应，请重新训练压缩网格')
    current_registry = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    recorded_runtime = identity.get('response_runtime_sha256')
    if (identity.get('response_implementation_sha256') != current_registry or
            recorded_runtime != runtime_fingerprint(response)):
        raise ValueError('Hybrid 响应推理实现已变化，请重新训练压缩网格')
