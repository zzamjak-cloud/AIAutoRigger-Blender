"""자동 리깅 평가 실행기 (격리 개발 프로필 Blender 에서 실행).

    scripts/dev_run.sh --background --python scripts/eval_run.py -- [--data DIR] [--synthetic N] [--out DIR]

- 합성 세트: 테스트 픽스처 비율을 시드 고정 난수로 바꾼 2족·4족 메시 (정답 자동 생성)
- 실데이터: DIR/<범주>/<모델>.fbx|.glb|.gltf 의 리깅된 모델에서 정답 관절을 추출하고
  리그를 제거한 뒤 재리깅해 비교한다. 범주 이름에 'quad' 가 있으면 4족으로 강제한다.
결과: <out>/report.json, <out>/report.md
"""

import argparse
import json
import pathlib
import random
import sys
import time
import traceback
from dataclasses import asdict

import bpy

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
from core import evaluation  # noqa: E402
import humanoid  # noqa: E402
import quadruped  # noqa: E402

# 우리 메타리그 본 head → 표준 관절명
METARIG_JOINTS = {
    "BIPED": {
        "thigh": "hip", "shin": "knee", "foot": "ankle",
        "upper_arm": "shoulder", "forearm": "elbow", "hand": "wrist",
    },
    "QUADRUPED": {
        "thigh": "r_hip", "shin": "r_knee", "foot": "r_hock",
        "front_thigh": "f_shoulder", "front_shin": "f_elbow", "front_foot": "f_wrist",
    },
}
METARIG_HEAD = {"BIPED": "spine.006", "QUADRUPED": "spine.011"}
MODEL_EXTS = {".fbx", ".glb", ".gltf"}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=pathlib.Path)
    p.add_argument("--synthetic", type=int, default=6, help="체형별 합성 케이스 수")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", type=pathlib.Path, default=ROOT / "dist" / "eval")
    return p.parse_args(argv)


def estimated_joints(kind):
    state = bpy.context.scene.airig
    metarig = bpy.data.objects[state.metarig_name]
    mw = metarig.matrix_world
    out = {}
    for bone in metarig.data.bones:
        base, _, side = bone.name.rpartition(".")
        if side in ("L", "R") and base in METARIG_JOINTS[kind]:
            out[f"{METARIG_JOINTS[kind][base]}_{side}"] = tuple(mw @ bone.head_local)
    head = metarig.data.bones.get(METARIG_HEAD[kind])
    if head is not None:
        out["head_base"] = tuple(mw @ head.head_local)
    return out


def rest_displacement(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    d = max(((obj.matrix_world @ me.vertices[i].co) - (obj.matrix_world @ v.co)).length
            for i, v in enumerate(obj.data.vertices))
    ev.to_mesh_clear()
    return d


def rig_case(result, obj, truth, kind):
    """활성 메시를 자동 리깅하고 결과를 result 에 채운다."""
    state = bpy.context.scene.airig
    state.body_type = kind if kind else "AUTO"
    bpy.context.view_layer.objects.active = obj
    for o in bpy.context.view_layer.objects:
        o.select_set(o == obj)
    size = max(obj.dimensions)
    t0 = time.perf_counter()
    try:
        ret = bpy.ops.airig.auto_rig()
    except RuntimeError as exc:
        result.error = str(exc).splitlines()[-1][:120]
        return
    finally:
        result.seconds = time.perf_counter() - t0
    if ret != {"FINISHED"}:
        result.error = "auto_rig 취소"
        return
    result.kind = state.detected_type
    est = estimated_joints(result.kind)
    result.joint_errors = evaluation.joint_errors(est, truth, size)
    result.unweighted_ratio = state.unweighted_vertices / max(1, len(obj.data.vertices))
    result.rest_displacement = rest_displacement(obj) / size
    result.ok = True


def make_mesh(name, verts, tris):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], tris)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    mod = obj.modifiers.new("remesh", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = 0.015
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj


def synthetic_cases(n, seed):
    rng = random.Random(seed)
    for i in range(n):
        cfg = dict(head=rng.uniform(0.8, 2.2), leg=rng.uniform(0.5, 1.2), arm=rng.uniform(0.6, 1.2),
                   arm_angle=rng.uniform(0.0, 45.0))
        yield "synthetic_biped", f"biped_{i:02d}", "BIPED", humanoid.build_from, cfg
    for i in range(n):
        cfg = dict(leg=rng.uniform(0.5, 1.3), head=rng.uniform(0.8, 2.0), tail=rng.uniform(0.0, 1.2),
                   body=rng.uniform(0.8, 1.4))
        yield "synthetic_quadruped", f"quad_{i:02d}", "QUADRUPED", quadruped.build_from, cfg


def run_synthetic(n, seed, results):
    for category, name, kind, builder, cfg in synthetic_cases(n, seed):
        bpy.ops.wm.read_homefile(use_empty=True)
        verts, tris, gt = builder(cfg)
        truth = {k: v for k, v in gt.items() if k != "tail_tip" and k != "head_top"}
        if kind == "QUADRUPED":
            truth.pop("head_base", None)
        obj = make_mesh(name, verts, tris)
        r = evaluation.CaseResult(name, category)
        # 체형 자동 판별 자체도 평가 대상이므로 AUTO 로 실행하고 결과 체형을 검사한다
        rig_case(r, obj, truth, None)
        if r.ok and r.kind != kind:
            r.ok, r.error = False, f"체형 오판별 {r.kind}"
        results.append(r)
        print(f"[eval] {category}/{name}: {'OK' if r.ok else r.error} {r.mean_error}")


def import_model(path):
    ext = path.suffix.lower()
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        bpy.ops.import_scene.gltf(filepath=str(path))


def strip_rig(armature):
    """정답 관절을 추출하고 리그를 제거한 단일 메시를 반환한다."""
    armature.data.pose_position = "REST"
    bpy.context.view_layer.update()
    mw = armature.matrix_world
    bones = [(b.name, tuple(mw @ b.head_local), tuple(mw @ b.tail_local)) for b in armature.data.bones]
    meshes = [o for o in bpy.data.objects if o.type == "MESH"
              and any(m.type == "ARMATURE" and m.object == armature for m in o.modifiers)]
    if not meshes:
        raise RuntimeError("리그에 바인딩된 메시가 없습니다.")
    for obj in meshes:
        for m in [m for m in obj.modifiers if m.type == "ARMATURE"]:
            obj.modifiers.remove(m)
        obj.vertex_groups.clear()
        mw_obj = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = mw_obj
    for o in bpy.context.view_layer.objects:
        o.select_set(o in meshes)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    merged = bpy.context.view_layer.objects.active
    # 뷰 레이어 순회 중 무효 참조가 생기지 않도록 아마추어는 마지막에 제거한다
    bpy.data.objects.remove(armature)
    return merged, bones


def run_dataset(data_dir, results):
    for path in sorted(p for p in data_dir.rglob("*") if p.suffix.lower() in MODEL_EXTS):
        category = path.parent.relative_to(data_dir).as_posix() or "root"
        kind = "QUADRUPED" if "quad" in category.lower() else None
        r = evaluation.CaseResult(path.stem, category)
        try:
            bpy.ops.wm.read_homefile(use_empty=True)
            import_model(path)
            arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
            if not arms:
                raise RuntimeError("아마추어가 없습니다.")
            armature = max(arms, key=lambda o: len(o.data.bones))
            obj, bones = strip_rig(armature)
            truth = evaluation.map_bones(bones, kind or "BIPED")
            if len(truth) < 4:
                raise RuntimeError(f"정답 관절 매핑 부족 ({len(truth)}개)")
            rig_case(r, obj, truth, kind)
        except Exception as exc:  # 한 모델 실패가 전체 평가를 멈추지 않게 기록만 한다
            traceback.print_exc()
            r.ok, r.error = False, str(exc).splitlines()[-1][:120]
        results.append(r)
        print(f"[eval] {category}/{path.name}: {'OK' if r.ok else r.error} {r.mean_error}")


def main():
    args = parse_args()
    results = []
    if args.synthetic > 0:
        run_synthetic(args.synthetic, args.seed, results)
    if args.data:
        run_dataset(args.data, results)
    summary = evaluation.summarize(results)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(
        json.dumps({"summary": summary, "cases": [asdict(r) for r in results]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.out / "report.md").write_text(evaluation.to_markdown(results, summary), encoding="utf-8")
    print(f"[eval] report: {args.out / 'report.md'}")
    for cat, s in summary.items():
        print(f"[eval] {cat}: {s['success']}/{s['cases']} mean={s['mean_joint_error']}")


main()
