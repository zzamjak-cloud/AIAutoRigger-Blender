"""모션 템플릿 저장소 단위 테스트 (bpy 비의존): 이름 규칙, 버전·히스토리, 내장/사용자 우선순위, 체형별 타입 고르기."""

import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from core import motion_template as T  # noqa: E402


def make(type_name="Zombie_Thin", name="walk", loop=True, frames=59, body=None, marker=0.0):
    return {"format": T.FORMAT, "type": type_name, "name": name, "loop": loop, "frames": frames,
            "body": body or {"leg": 0.6, "arm": 0.8, "height": 2.0, "width": 1.2, "depth": 0.5},
            "channels": [{"path": 'pose.bones["torso"].location', "bone": "torso", "prop": "location", "space": "leg",
                          "size": 3, "keys": [{"t": 0.0, "v": [0.0, 0.0, marker], "ip": "BEZIER"}]}]}


class NamesTest(unittest.TestCase):
    def test_motion_name_strips_character_prefix(self):
        prefixes = ("Zombie_Thin", "Zombie_Thin_rig")
        self.assertEqual(T.motion_name("Zombie_Thin_Attack_R", prefixes), "Attack_R")
        self.assertEqual(T.motion_name("Zombie_Thin_rig_death_zombie", prefixes), "death_zombie")
        self.assertEqual(T.motion_name("Zombie_Thin", prefixes), "Zombie_Thin", "접두사뿐이면 그대로")
        self.assertEqual(T.motion_name("my walk!", ()), "my_walk")
        self.assertEqual(T.safe_name("  ", "Default"), "Default")

    def test_validate_rejects_other_files(self):
        with self.assertRaises(ValueError):
            T.validate({"keys": []})
        with self.assertRaises(ValueError):
            T.validate({**make(), "channels": []})


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="airig_tpl_"))
        self.builtin = pathlib.Path(tempfile.mkdtemp(prefix="airig_tpl_builtin_"))
        patcher = mock.patch.object(T, "BUILTIN_DIR", self.builtin)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_save_versions_and_history(self):
        p1 = T.save(self.tmp, make(marker=1.0))
        self.assertEqual(json.loads(p1.read_text(encoding="utf-8"))["version"], 1)
        T.save(self.tmp, make(marker=2.0))
        T.save(self.tmp, make(marker=3.0))
        cur = T.load(self.tmp)[("Zombie_Thin", "walk")]
        self.assertEqual(cur["version"], 3)
        self.assertEqual(cur["channels"][0]["keys"][0]["v"][2], 3.0, "최신 등록본이 현재 버전")
        hist = T.history(self.tmp, "Zombie_Thin", "walk")
        self.assertEqual([p.name for p in hist], ["walk.v1.json", "walk.v2.json"])
        self.assertEqual(json.loads(hist[0].read_text(encoding="utf-8"))["channels"][0]["keys"][0]["v"][2], 1.0)
        self.assertNotIn(("Zombie_Thin", "_history"), T.load(self.tmp), "히스토리는 목록에 나오지 않는다")

    def test_version_skips_history_and_keys_by_folder(self):
        for marker in (1.0, 2.0, 3.0):
            T.save(self.tmp, make(marker=marker))
        # 히스토리의 v1 을 현재 파일로 복원한 뒤 다시 등록해도 새 버전은 히스토리의 어떤 버전보다 높다
        cur = self.tmp / "Zombie_Thin" / "walk.json"
        cur.write_text((self.tmp / "Zombie_Thin" / "_history" / "walk.v1.json").read_text(encoding="utf-8"), encoding="utf-8")
        T.save(self.tmp, make(marker=4.0))
        self.assertEqual(T.load(self.tmp)[("Zombie_Thin", "walk")]["version"], 3, "v1 복원본 → 히스토리 최대 v2 다음")
        names = sorted(p.name for p in T.history(self.tmp, "Zombie_Thin", "walk"))
        self.assertEqual(len(names), len(set(names)), "히스토리 파일 이름이 겹치지 않는다")
        # 폴더를 복사해 새 타입을 만들면 JSON 안의 type 과 무관하게 폴더 이름이 타입이다
        import shutil
        shutil.copytree(self.tmp / "Zombie_Thin", self.tmp / "Zombie_Fat")
        data = T.load(self.tmp)
        self.assertIn(("Zombie_Fat", "walk"), data)
        self.assertEqual(data[("Zombie_Thin", "walk")]["channels"][0]["keys"][0]["v"][2], 4.0)
        self.assertFalse(list((self.tmp / "Zombie_Thin").glob(".*.tmp")), "임시 파일이 남지 않는다")

    def test_user_overrides_builtin_and_continues_version(self):
        (self.builtin / "Zombie_Thin").mkdir()
        (self.builtin / "Zombie_Thin" / "walk.json").write_text(json.dumps({**make(marker=9.0), "version": 4}), encoding="utf-8")
        (self.builtin / "Zombie_Thin" / "idle.json").write_text(json.dumps(make(name="idle")), encoding="utf-8")
        self.assertEqual(T.load(self.tmp)[("Zombie_Thin", "walk")]["_source"], "builtin")
        T.save(self.tmp, make(marker=5.0))
        data = T.load(self.tmp)
        self.assertEqual(data[("Zombie_Thin", "walk")]["_source"], "user")
        self.assertEqual(data[("Zombie_Thin", "walk")]["version"], 5, "내장 버전에서 이어서 올린다")
        self.assertEqual(data[("Zombie_Thin", "idle")]["_source"], "builtin")
        self.assertEqual(T.motions(data, "Zombie_Thin"), ["idle", "walk"])

    def test_nearest_type_by_body(self):
        thin = {"leg": 0.6, "arm": 0.8, "height": 2.0, "width": 1.2, "depth": 0.5}
        fat = {"leg": 0.45, "arm": 0.6, "height": 1.6, "width": 1.5, "depth": 1.0}
        T.save(self.tmp, make("Zombie_Thin", "walk", body=thin))
        T.save(self.tmp, make("Zombie_Fat", "walk", body=fat))
        T.save(self.tmp, make("Zombie_Fat", "crawl", body=fat))
        data = T.load(self.tmp)
        self.assertEqual(T.types(data), ["Zombie_Fat", "Zombie_Thin"])
        chubby = {"leg": 0.5, "arm": 0.62, "height": 1.7, "width": 1.5, "depth": 0.9}
        self.assertEqual(T.nearest_type(data, chubby, "walk"), "Zombie_Fat")
        self.assertEqual(T.nearest_type(data, {**thin, "height": 2.05}, "walk"), "Zombie_Thin")
        self.assertEqual(T.nearest_type(data, thin, "crawl"), "Zombie_Fat", "그 동작이 있는 타입 중에서 고른다")
        self.assertEqual(T.resolve(data, T.AUTO_TYPE, "walk", chubby)["type"], "Zombie_Fat")
        self.assertEqual(T.motions(data, T.AUTO_TYPE), ["crawl", "walk"])
        with self.assertRaises(KeyError):
            T.resolve(data, "Zombie_Thin", "crawl")


if __name__ == "__main__":
    unittest.main()
