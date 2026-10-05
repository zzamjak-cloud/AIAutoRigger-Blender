from . import ai_rig, analyze, animate, export, review, rig

classes = (*analyze.classes, *rig.classes, *ai_rig.classes, *review.classes, *animate.classes, *export.classes)
