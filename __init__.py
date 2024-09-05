bl_info = {
    "name": "Image Gallery Overlay",
    "author": "zvodd",
    "version": (1, 0),
    "blender": (3, 60, 0),
    "location": "View > Image Editor > Image Gallery Overlay",
    "description": "Adds an overlay to display and select images in the Image Editor",
    "category": "Image",
}

import bpy

# Include *all* modules in this package for proper reloading.
#   * All modules *must* have a register() and unregister() method!
#   * Dependency *must* come *before* modules that use them in the list!
register, unregister = bpy.utils.register_submodule_factory(__package__, (
    'gallerymodal',
))