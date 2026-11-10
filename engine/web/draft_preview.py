"""Read-only edits of a completed fit's effective native color parameters.

The measured context does not retain the camera's three-endpoint selection
weights. Editing therefore follows the training export's shared-endpoint
policy rather than silently simulating only one endpoint.
"""
import copy
import json
import struct
import time
from pathlib import Path

import numpy as np

import core


FIELDS = ('cc1_delta', 'block13', 'gamma_native_129')


def build_model(model, stored, entry):
    """Apply native-unit edit deltas while retaining exact fitted raw values.

Unchanged values must not incur a second BIN quantization. In particular CC1
gain shorts and Gamma ordinates can be odd before their export division by 2.
The block13 fields already have the exported packed bit representation.
"""
    from edit_parameter_context import ParameterContext

    if not isinstance(entry, dict) or any(field not in entry for field in FIELDS):
        raise ValueError('草稿必须包含 Gamma、CC1 和 block13 完整参数')
    checked = copy.deepcopy(stored)
    checked.update({field: copy.deepcopy(entry[field]) for field in FIELDS})
    core.compiler.pack(core.config([checked]))

    old_cc, cc = [np.asarray(value['cc1_delta'], dtype=np.int64) for value in (stored, checked)]
    old_block, block = [np.asarray(value['block13'], dtype=np.int64) for value in (stored, checked)]
    old_gamma, gamma = [np.asarray(value['gamma_native_129'], dtype=np.int64) for value in (stored, checked)]
    cc_delta, block_delta, gamma_delta = cc-old_cc, block-old_block, gamma-old_gamma
    if np.any(old_cc[1:]) or not np.all(old_block == old_block[0]):
        raise ValueError('此任务没有采用训练共同端点结构，无法可靠模拟独立端点')
    if np.any(cc_delta[1:]):
        raise ValueError('实时模拟仅支持训练 CC1 的 B 共同基值；A1/A2 差分请保持原值')
    if not np.all(block_delta == block_delta[0]):
        raise ValueError('实时模拟要求 block13 三端点同步调整；不能模拟独立端点选取权重')

    changed = dict(cc1=int(np.count_nonzero(cc_delta[0])),
                   block13=int(np.count_nonzero(block_delta[0])),
                   gamma=int(np.count_nonzero(gamma_delta[:128])))
    audit = dict(
        schema='r5-effective-native-draft/1', changed=changed,
        native_unit_mapping=dict(cc1_raw_order=[3,0,1,2,7,4,5,6],
                                 cc1_raw_delta_scales=[1,1,1,1,2,2,2,2],
                                 gamma_raw_delta_scale=2,
                                 block13='replace exported coefficient bits; preserve common fields and low padding bits'),
        shared_endpoints=True, original_fit_quantization_preserved=True,
        gamma_point128=dict(edited=bool(gamma_delta[128]),participates_in_simulation=False),
        ignored_parameters=['gamma_native_129[128]'] if gamma_delta[128] else [],
        simulation_note='使用本任务训练有效参数；CC1 共用 B，block13 三端点同步。Gamma 第129点仅供导出，不参与此模拟。',
        writes_job=False, writes_binary=False, camera_verified=False)
    if not any(changed.values()):
        return model, audit

    raw_cc = model.coefficients().astype(np.int64)
    order = [3,0,1,2,7,4,5,6]
    raw_cc += cc_delta[0,order] * np.asarray([1]*4+[2]*4)
    raw_gamma = np.frombuffer(model.raw,dtype='<i4',count=128,offset=0x7d8).astype(np.int64)
    raw_gamma += gamma_delta[:128]*2
    payload = bytearray(model.raw[0xae:0xae+276])
    for sector, coefficient in np.argwhere(block_delta[0] != 0):
        at = 24+2*(16*int(coefficient)+(int(sector)^1))
        previous = struct.unpack_from('<H',payload,at)[0]
        value = (int(block[0,sector,coefficient]) << 2) & 0xfffc
        struct.pack_into('<H',payload,at,value | (previous & 3))
    result = ParameterContext(model).build(matrix_payload=bytes(payload),
                                           cc1=raw_cc,gamma_y=raw_gamma)
    return result, audit


def diagnostics(output, entry, pc=False, grid_key=None, mode='preview'):
    """Return existing diagnostic groups plus matched draft preview colors."""
    import baseline
    if mode not in ('preview','full'):
        raise ValueError('实时模拟模式必须为 preview 或 full')
    if type(pc) is not bool:
        raise ValueError('PC 补偿开关须为布尔值')
    output = Path(output)
    started = time.perf_counter()
    native = json.loads((output/'native_config.json').read_text())
    core.compiler.pack(native)
    if len(native['entries']) != 1:
        raise ValueError('实时模拟需要一个已完成的单滤镜训练任务')
    recipe, original = baseline.read_job(output)
    model, audit = build_model(original,native['entries'][0],entry)
    result = core.diagnostics(output,pc,grid_key,model_recipe=(recipe,model),
                              test_limit=4096 if mode == 'preview' else None,
                              include_preview=True,reference_model=original)
    result.update(draft=True,mode=mode,entry_audit=audit,
                  simulation_note=audit['simulation_note'],
                  elapsed_ms=round((time.perf_counter()-started)*1000,1))
    result['samples']['policy']='fixed evenly spaced independent test subset; anchors remain complete' if mode == 'preview' else 'complete independent test set; anchors reported separately'
    return result
