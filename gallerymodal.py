import bpy
import gpu
from gpu_extras.batch import batch_for_shader
import mathutils
import math

# from pprint import pprint ###DEBUG

class ImageGalleryOverlay(bpy.types.Operator):
    bl_idname = "image.image_gallery_overlay"
    bl_label = "Image Gallery Overlay"

    _draw_handler = None
    selected_image = None
    grid_data = None
    columns, row_height, column_width, spacing = None, None, None, None
    edarea = None

    def clean_up(self):
        if self._draw_handler is not None:
            bpy.types.SpaceImageEditor.draw_handler_remove(self._draw_handler, 'WINDOW')
        self._draw_handler = None
        self.selected_image = None
        self.grid_data = None
        self.edarea = None

    def modal(self, context, event):
        #lock the interactions to the IMAGE_EDITOR area
        if context.area != self.edarea:
            return {'PASS_THROUGH'}

        context.area.tag_redraw()

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self.clean_up()
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # pprint((event.mouse_x, event.mouse_y)) ###DEBUG

            for image_name, image_rect in self.grid_data.items():
                
                if self.is_image_clicked(image_rect, event.mouse_x, event.mouse_y):
                    self.selected_image = bpy.data.images[image_name]
                    print(self.selected_image.name)
                    self.edarea.spaces.active.image = self.selected_image
                    self.clean_up()
                    return {'FINISHED'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        if context.area.type == 'IMAGE_EDITOR':
            self.edarea = context.area
            #self.cached_region = context.region
            self.grid_data = self.calculate_grid(context)
            # pprint(self.grid_data) ###DEBUG

            args = (self.columns, self.row_height, self.column_width, self.spacing, self.grid_data)
            self._draw_handler = bpy.types.SpaceImageEditor.draw_handler_add(self.draw_callback_px, args, 'WINDOW', 'POST_PIXEL')
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a ImageEditor")
            return {'CANCELLED'}

    def calculate_grid(self, context):
        grid_data = {}
        max_width = 200
        max_height = 200
        imgs = [x for x in bpy.data.images if x.type != 'RENDER_RESULT']

        for image in imgs:
            w, h = image.size
            max_width = min(max_width, w)
            max_height = min(max_height, h)
        
        self.columns = int(math.sqrt(len(imgs)))
        self.row_height = max_height
        self.column_width = max_width
        self.spacing = 10
        
        y_offset = 0
        for i, image in enumerate(imgs):
            w, h = image.size
            x = (i % self.columns) * (self.column_width + self.spacing)
            y = y_offset + (i // self.columns) * (self.row_height + self.spacing)
            
            # Ensure the image doesn't go out of bounds
            # actually don't want this... would like to support vertical scrolling
            x = max(0, min(x, self.edarea.width - self.column_width))
            y = max(0, min(y, self.edarea.height - self.row_height))
            
            grid_data[image.name] = (x, y, self.column_width, self.row_height)
        
        return grid_data


    def draw_callback_px(self, columns, row_height, column_width, spacing, grid_data):
        # Using a ref to `self` was throwing a lot of errors...
        # So just inject everything we need into args. Not sure if its actually neccisary, though.
        shader = gpu.shader.from_builtin('IMAGE')

        y_offset = 0
        for image_name, rect in grid_data.items():
            texture = gpu.texture.from_image(bpy.data.images[image_name])
            
            x, y, width, height = rect
            
            vertices = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
            indices = [(0, 1, 2), (0, 2, 3)]
            batch = batch_for_shader(shader, 'TRIS', {"pos": vertices, "texCoord": [(0, 0), (1, 0), (1, 1), (0, 1)]}, indices=indices)
            
            shader.uniform_sampler("image", texture)
            
            shader.bind()
            batch.draw(shader)

    def is_image_clicked(self, image_rect, mouse_x, mouse_y):
        #TODO remap the dimensions of the screen area to account for any changes. 
        x, y, width, height = image_rect
        mouse_x -= self.edarea.x
        mouse_y -= self.edarea.y
        return (
            x <= mouse_x <= x + width and 
            y <= mouse_y <= y + height
        )
        return False

def menu_func(self, context):
    self.layout.operator(ImageGalleryOverlay.bl_idname, text=ImageGalleryOverlay.bl_label)

# Register and add to the "view" menu (required to also use F3 search "Image Gallery Overlay" for quick access).
def register():
    bpy.utils.register_class(ImageGalleryOverlay)
    bpy.types.IMAGE_MT_view.append(menu_func)

def unregister():
    bpy.utils.unregister_class(ImageGalleryOverlay)
    bpy.types.IMAGE_MT_view.remove(menu_func)

if __name__ == "__main__":
    register()
