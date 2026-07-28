import bpy
import gpu
from gpu_extras.batch import batch_for_shader
import mathutils
import math

class ImageGalleryOverlay(bpy.types.Operator):
    bl_idname = "image.image_gallery_overlay"
    bl_label = "Image Gallery Overlay"

    _draw_handler = None
    edarea = None
    columns = 0
    spacing = 10.0
    bottom_padding = 0.0  # Will be calculated to fit one extra row

    # Persistent settings across invocations
    _cell_size = 200.0
    _scroll_y = 0.0
    _initialized = False

    # Singular Instance Lock
    _instance = None

    @property
    def cell_size(self): return ImageGalleryOverlay._cell_size
    @cell_size.setter
    def cell_size(self, val): ImageGalleryOverlay._cell_size = val

    @property
    def scroll_y(self): return ImageGalleryOverlay._scroll_y
    @scroll_y.setter
    def scroll_y(self, val): ImageGalleryOverlay._scroll_y = val

    @classmethod
    def is_running(cls):
        if cls._instance is not None:
            if not hasattr(cls._instance, 'modal'):
                cls._instance = None
                return False
        return cls._instance is not None

    def clean_up(self):
        if self._draw_handler is not None:
            bpy.types.SpaceImageEditor.draw_handler_remove(self._draw_handler, 'WINDOW')
        self._draw_handler = None
        self.edarea = None
        ImageGalleryOverlay._instance = None

    def get_relative_mouse_coords(self, context, event):
        mx, my = event.mouse_x, event.mouse_y
        for region in context.area.regions:
            if region.type == 'WINDOW':
                mx -= region.x
                my -= region.y
                return mx, my
        mx -= context.area.x
        my -= context.area.y
        return mx, my

    def get_window_region(self, context):
        for region in context.area.regions:
            if region.type == 'WINDOW':
                return region
        return None

    def modal(self, context, event):
        if self.edarea is None or not self.edarea.as_pointer():
            self.clean_up()
            return {'CANCELLED'}

        if context.area != self.edarea:
            return {'PASS_THROUGH'}

        context.area.tag_redraw()

        # Track changes to viewport size or UI layout
        win_region = self.get_window_region(context)
        if win_region:
            if hasattr(self, '_last_w') and hasattr(self, '_last_h') and hasattr(self, '_last_rx') and hasattr(self, '_last_ry'):
                if self._last_w != win_region.width or self._last_h != win_region.height or self._last_rx != win_region.x or self._last_ry != win_region.y:
                    ImageGalleryOverlay._initialized = False 
                    self.grid_data = self.calculate_grid(context)
            self._last_w = win_region.width
            self._last_h = win_region.height
            self._last_rx = win_region.x
            self._last_ry = win_region.y

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self.clean_up()
            return {'CANCELLED'}

        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.ctrl:
            delta = 20.0 if event.type == 'WHEELUPMOUSE' else -20.0
            self.cell_size = max(50.0, min(self.cell_size + delta, 500.0))
            ImageGalleryOverlay._initialized = False 
            self.grid_data = self.calculate_grid(context)
            return {'RUNNING_MODAL'}

        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and not event.ctrl:
            scroll_speed = context.region.height * 0.1
            delta = scroll_speed if event.type == 'WHEELUPMOUSE' else -scroll_speed
            self.scroll_y += delta
            self.grid_data = self.calculate_grid(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            mx, my = self.get_relative_mouse_coords(context, event)

            for image_name, image_rect in self.grid_data.items():
                x, y, w, h = image_rect
                if x <= mx <= x + w and y <= my <= y + h:
                    self.edarea.spaces.active.image = bpy.data.images[image_name]
                    self.clean_up()
                    return {'FINISHED'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        if ImageGalleryOverlay.is_running():
            self.report({'WARNING'}, "Gallery overlay is already running")
            return {'CANCELLED'}

        if context.area.type == 'IMAGE_EDITOR':
            ImageGalleryOverlay._instance = self
            self.edarea = context.area
            
            win_region = self.get_window_region(context)
            if win_region:
                self._last_w = win_region.width
                self._last_h = win_region.height
                self._last_rx = win_region.x
                self._last_ry = win_region.y
                
            self.grid_data = self.calculate_grid(context)
            
            self._draw_handler = bpy.types.SpaceImageEditor.draw_handler_add(
                self.draw_callback_px, 
                (self,), 
                'WINDOW', 
                'POST_PIXEL'
            )
            
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be an Image Editor")
            return {'CANCELLED'}

    def calculate_grid(self, context):
        grid_data = {}
        imgs = [x for x in bpy.data.images if x.type != 'RENDER_RESULT']
        
        win_region = self.get_window_region(context)
        if not win_region:
            return {}
            
        viewport_width = win_region.width
        viewport_height = win_region.height
        
        self.columns = max(1, int(viewport_width // (self.cell_size + self.spacing)))
        
        active_image = self.edarea.spaces.active.image
        active_idx = imgs.index(active_image) if active_image in imgs else 0
        
        rows = math.ceil(len(imgs) / self.columns) if self.columns > 0 else 1
        
        # Padding equivalent to one row so you can always scroll the last row completely into view
        self.bottom_padding = self.cell_size + self.spacing
        total_height = rows * (self.cell_size + self.spacing) + self.bottom_padding
        
        # The absolute Y position of the very top of the window region (in screen space)
        top_y = win_region.y + win_region.height
        
        if not ImageGalleryOverlay._initialized:
            active_row = active_idx // self.columns
            self.scroll_y = (viewport_height * 0.5) - (active_row * (self.cell_size + self.spacing)) - (self.cell_size / 2.0)
            ImageGalleryOverlay._initialized = True

        if total_height > viewport_height:
            # Lower bound allows enough scroll to bypass the bottom padding entirely
            self.scroll_y = max(viewport_height - total_height, min(self.scroll_y, self.cell_size + 50))
        else:
            self.scroll_y = 0
            
        for i, image in enumerate(imgs):
            col = i % self.columns
            row = i // self.columns
            
            # X is offset by win_region.x so it respects left tools panel
            # Y starts at win_region.y (absolute screen space bottom of region) + height (top) minus row
            x = win_region.x + col * (self.cell_size + self.spacing)
            y = top_y - (row + 1) * (self.cell_size + self.spacing) + self.scroll_y
            
            grid_data[image.name] = (x, y, self.cell_size, self.cell_size)
            
        return grid_data

    def draw_callback_px(self, op_instance):
        shader = gpu.shader.from_builtin('IMAGE')
        
        for image_name, rect in op_instance.grid_data.items():
            x, y, w, h = rect
                        
            image = bpy.data.images[image_name]
            img_w, img_h = image.size
            
            if img_w > 0 and img_h > 0:
                ratio = min(w / img_w, h / img_h)
                draw_w = img_w * ratio
                draw_h = img_h * ratio
                
                offset_x_img = (w - draw_w) / 2.0
                offset_y_img = (h - draw_h) / 2.0
                
                px = x + offset_x_img
                py = y + offset_y_img
                
                vertices = [(px, py), (px + draw_w, py), (px + draw_w, py + draw_h), (px, py + draw_h)]
                indices = [(0, 1, 2), (0, 2, 3)]
                tex_coords = [(0, 0), (1, 0), (1, 1), (0, 1)]
                
                try:
                    texture = gpu.texture.from_image(image)
                    batch = batch_for_shader(shader, 'TRIS', {"pos": vertices, "texCoord": tex_coords}, indices=indices)
                    shader.uniform_sampler("image", texture)
                    shader.bind()
                    batch.draw(shader)
                except Exception:
                    pass

def menu_func(self, context):
    self.layout.operator(ImageGalleryOverlay.bl_idname, text=ImageGalleryOverlay.bl_label)

def register():
    bpy.utils.register_class(ImageGalleryOverlay)
    bpy.types.IMAGE_MT_view.append(menu_func)

def unregister():
    if ImageGalleryOverlay.is_running():
        ImageGalleryOverlay._instance.clean_up()
    bpy.utils.unregister_class(ImageGalleryOverlay)
    bpy.types.IMAGE_MT_view.remove(menu_func)

if __name__ == "__main__":
    register()