from . import ai_rig, analyze, export, review, rig

classes = (*analyze.classes, *rig.classes, *ai_rig.classes, *review.classes, *export.classes)
