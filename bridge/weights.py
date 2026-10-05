"""정점 그룹 웨이트 라플라시안 스무딩."""

FACTOR = 0.5


def smooth_group(mesh_obj, group_name, iterations, factor=FACTOR):
    """이웃 평균으로 한 그룹의 웨이트를 부드럽게 한다. 그룹이 없으면 False."""
    vg = mesh_obj.vertex_groups.get(group_name)
    if vg is None:
        return False
    me = mesh_obj.data
    n = len(me.vertices)
    neighbors = [[] for _ in range(n)]
    for e in me.edges:
        a, b = e.vertices
        neighbors[a].append(b)
        neighbors[b].append(a)
    w = [0.0] * n
    for v in me.vertices:
        for g in v.groups:
            if g.group == vg.index:
                w[v.index] = g.weight
    for _ in range(iterations):
        w = [
            (1.0 - factor) * w[i] + factor * (sum(w[j] for j in nb) / len(nb)) if nb else w[i]
            for i, nb in enumerate(neighbors)
        ]
    # Armature 모디파이어가 정점별 총합으로 정규화하므로 이 그룹만 갱신해도 된다
    for i, value in enumerate(w):
        if value > 1e-4:
            vg.add([i], min(1.0, value), "REPLACE")
        else:
            vg.remove([i])
    return True


def _set_exclusive(mesh_obj, verts, group, deform_names):
    """정점들을 group 에 1.0, 다른 디폼 그룹에서는 제거한다 (눈동자·입속 조각처럼 통째로 움직일 부분)."""
    vg = mesh_obj.vertex_groups.get(group)
    if vg is None:
        return
    for other in mesh_obj.vertex_groups:
        if other.name in deform_names and other.name != group:
            other.remove(list(verts))
    vg.add(list(verts), 1.0, "REPLACE")


def apply_face_weights(mesh_obj, face, islands):
    """자동 웨이트 위에 턱·눈 웨이트를 직접 덮어쓴다.

    열 확산 웨이트는 턱이 볼·머리 위쪽까지 끌고 가므로, 입술 선 아래·회전축 앞 영역에 턱 비율 w 를 주고
    다른 디폼 그룹은 (1-w) 배로 줄인다. 눈동자 조각은 눈 본에, 입술 선 아래의 입속 조각(아랫니·혀)은 턱에 통째로 붙인다.
    """
    from ..core.face import jaw_weight

    deform = {g.name for g in mesh_obj.vertex_groups if g.name.startswith("DEF-")}
    mw = mesh_obj.matrix_world
    me = mesh_obj.data
    rigid = set()
    for eye in face.eyes:
        # 저장된 섬 번호는 메시를 편집하면 어긋날 수 있으므로 중심·반지름이 맞는지 확인한다
        if not (0 <= eye.island < len(islands)):
            continue
        _verts, center, radius = islands[eye.island]
        if sum((a - b) ** 2 for a, b in zip(center, eye.center)) ** 0.5 > 0.5 * max(eye.radius, 1e-6) \
                or abs(radius - eye.radius) > 0.5 * max(eye.radius, 1e-6):
            continue
        verts = islands[eye.island][0]
        group = f"DEF-eye.{eye.side}"
        _set_exclusive(mesh_obj, verts, group, deform)
        rigid.update(verts)
        # 열 확산 웨이트가 눈 본 영향을 눈두덩이·이마에도 퍼뜨리므로 눈동자 밖에서는 지운다
        vg = mesh_obj.vertex_groups.get(group)
        if vg is not None:
            keep = set(verts)
            stray = [v.index for v in me.vertices if v.index not in keep and any(g.group == vg.index for g in v.groups)]
            vg.remove(stray)
            head = mesh_obj.vertex_groups.get("DEF-spine.006")
            deform_idx = {g.index for g in mesh_obj.vertex_groups if g.name in deform}
            orphans = [i for i in stray if not any(g.group in deform_idx and g.weight > 1e-4 for g in me.vertices[i].groups)]
            if head is not None and orphans:
                head.add(orphans, 1.0, "REPLACE")
    jaw = face.jaw
    if jaw is None or "DEF-jaw" not in mesh_obj.vertex_groups:
        return
    jaw_vg = mesh_obj.vertex_groups["DEF-jaw"]
    for verts, center, radius in islands:
        if len(islands) > 1 and len(verts) < 0.2 * len(me.vertices) and center[2] < jaw.lip_z and jaw_weight(center, jaw) > 0.5:
            _set_exclusive(mesh_obj, verts, "DEF-jaw", deform)
            rigid.update(verts)
    groups = {g.index: g for g in mesh_obj.vertex_groups if g.name in deform}
    head = mesh_obj.vertex_groups.get("DEF-spine.006")
    drop, orphans = [], []
    for v in me.vertices:
        if v.index in rigid:
            continue
        w = jaw_weight(tuple(mw @ v.co), jaw)
        others = [(groups[g.group], g.weight) for g in v.groups
                  if g.group in groups and g.group != jaw_vg.index and g.weight > 0.0]
        total = sum(gw for _g, gw in others)
        if w <= 0.0:
            drop.append(v.index)
            # 열 확산 웨이트가 턱에만 있던 정점은 빠지면 무웨이트가 되므로 머리에 붙인다
            if total <= 1e-6:
                orphans.append(v.index)
            continue
        if total <= 1e-6 and head is not None:
            others, total = [(head, 1.0)], 1.0
        # 턱 비율이 정확히 w 가 되도록 나머지를 (1-w) 합으로 다시 나눈다 (기존 턱 몫은 버린다)
        for grp, gw in others:
            grp.add([v.index], gw / total * (1.0 - w), "REPLACE")
        jaw_vg.add([v.index], w, "REPLACE")
    if drop:
        jaw_vg.remove(drop)
    if orphans and head is not None:
        head.add(orphans, 1.0, "REPLACE")


def count_unweighted(mesh_obj, deform_names):
    idx = {g.index for g in mesh_obj.vertex_groups if g.name in deform_names}
    return sum(1 for v in mesh_obj.data.vertices if not any(g.group in idx and g.weight > 1e-4 for g in v.groups))
