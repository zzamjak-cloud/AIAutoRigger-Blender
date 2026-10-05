import bpy

from . import operators, preferences, properties, ui

_classes = (*preferences.classes, *properties.classes, *operators.classes, *ui.classes)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    properties.register_props()
    preferences.autofill_on_register()


def unregister():
    properties.unregister_props()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
