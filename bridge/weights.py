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
