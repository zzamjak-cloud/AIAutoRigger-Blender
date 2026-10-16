from . import ai_rig, analyze, animate, export, review, rig, template

classes = (*analyze.classes, *rig.classes, *ai_rig.classes, *review.classes, *animate.classes, *template.classes, *export.classes)
