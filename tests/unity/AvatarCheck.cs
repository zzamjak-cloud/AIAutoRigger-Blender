// 내보낸 FBX 를 Humanoid 로 임포트해 Unity 아바타 자동 매핑이 유효한지 검사한다 (배치 모드 전용).
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

public static class AvatarCheck
{
    static readonly string[] Required =
    {
        "Hips", "Spine", "Chest", "Neck", "Head",
        "LeftUpperArm", "LeftLowerArm", "LeftHand", "RightUpperArm", "RightLowerArm", "RightHand",
        "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "RightUpperLeg", "RightLowerLeg", "RightFoot",
    };

    public static void Run()
    {
        var path = AssetDatabase.FindAssets("t:Model").Select(AssetDatabase.GUIDToAssetPath).First(p => p.EndsWith(".fbx"));
        var importer = (ModelImporter)AssetImporter.GetAtPath(path);
        importer.animationType = ModelImporterAnimationType.Human;
        importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
        // 임포트 중 리그 오류(예: inbetween 본 회전 불일치)를 모은다
        var rigErrors = new System.Collections.Generic.List<string>();
        Application.LogCallback onLog = (msg, _st, _type) =>
        {
            if (msg.Contains("Rig Error") || msg.Contains("mis-match")) rigErrors.Add(msg);
        };
        Application.logMessageReceived += onLog;
        importer.SaveAndReimport();
        Application.logMessageReceived -= onLog;

        var avatar = AssetDatabase.LoadAllAssetsAtPath(path).OfType<Avatar>().FirstOrDefault();
        var human = importer.humanDescription.human;
        var mapped = human.ToDictionary(h => h.humanName, h => h.boneName);
        var missing = Required.Where(r => !mapped.ContainsKey(r)).ToArray();
        var wrong = Required.Where(r => mapped.ContainsKey(r) && mapped[r] != r).ToArray();
        bool ok = avatar != null && avatar.isValid && avatar.isHuman && missing.Length == 0 && wrong.Length == 0 && rigErrors.Count == 0;

        var optional = new[] { "Jaw", "LeftEye", "RightEye", "Left Thumb Proximal", "Left Index Proximal", "Left Middle Proximal", "Left Ring Proximal" }
            .Where(mapped.ContainsKey).Select(o => $"\"{o}:{mapped[o]}\"");
        var report = $"{{\"model\":\"{path}\",\"optional\":[{string.Join(",", optional)}],\"valid\":{(avatar != null && avatar.isValid).ToString().ToLower()}," +
                     $"\"human\":{(avatar != null && avatar.isHuman).ToString().ToLower()},\"mapped\":{mapped.Count}," +
                     $"\"missing\":[{string.Join(",", missing.Select(m => $"\"{m}\""))}]," +
                     $"\"mismatched\":[{string.Join(",", wrong.Select(m => $"\"{m}:{mapped[m]}\""))}]," +
                     $"\"rig_errors\":{rigErrors.Count}}}";
        foreach (var e in rigErrors) Debug.Log("[AvatarCheck] rig error: " + e);
        File.WriteAllText(Path.Combine(Directory.GetCurrentDirectory(), "avatar_report.json"), report);
        Debug.Log("[AvatarCheck] " + report);
        EditorApplication.Exit(ok ? 0 : 1);
    }
}
