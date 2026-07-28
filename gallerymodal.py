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
    grid_data = None
    columns = 0
    spacing = 10.0

    # Persistent settings across invocations
    _cell_size = 200.0
    _scroll_y = 0.0
    _initialized = False

    @property
    def cell_size(self): return ImageGalleryOverlay._cell_size
    @cell_size.setter
    def cell_size(self, val): ImageGalleryOverlay._cell_size = val

    @property
    def scroll_y(self): return ImageGalleryOverlay._scroll_y
    @scroll_y.setter
    def scroll_y(self, val): ImageGalleryOverlay._scroll_y = val

    def clean_up(self):
        if self._draw_handler is not None:
            bpy.types.SpaceImageEditor.draw_handler_remove(self._draw_handler, 'WINDOW')
        self._draw_handler = None
        self.edarea = None
        self.grid_data = None

    def get_relative_mouse_coords(self, context, event):
        """
        Safely converts window-relative mouse coordinates to region-relative ones.
        Fallbacks to manual subtractions if region/view2d APIs fail.
        """
        mx, my = event.mouse_x, event.mouse_y
        
        for region in context.area.regions:
            if region.type == 'WINDOW':
                mx -= region.x
                my -= region.y
                return mx, my
                
        # Safe fallback if region iteration fails for any reason
        mx -= context.area.x
        my -= context.area.y
        return mx, my

    def modal(self, context, event):
        if context.area != self.edarea:
            return {'PASS_THROUGH'}

        context.area.tag_redraw()

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self.clean_up()
            return {'CANCELLED'}

        # Ctrl + Wheel to zoom
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.ctrl:
            delta = 20.0 if event.type == 'WHEELUPMOUSE' else -20.0
            self.cell_size = max(50.0, min(self.cell_size + delta, 500.0))
            ImageGalleryOverlay._initialized = False # Reset to recenter on current view after zoom
            self.grid_data = self.calculate_grid(context)
            return {'RUNNING_MODAL'}

        # Wheel only to scroll
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and not event.ctrl:
            # Scale scroll speed with viewport height so it feels natural on 4K and 1080p
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
        if context.area.type == 'IMAGE_EDITOR':
            self.edarea = context.area
            self.grid_data = self.calculate_grid(context)
            
            # Using a tuple of the primitives to avoid persistent binding errors on unregister
            args = (self.cell_size, self.spacing, self.grid_data)
            self._draw_handler = bpy.types.SpaceImageEditor.draw_handler_add(self.draw_callback_px, args, 'WINDOW', 'POST_PIXEL')
            
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be an Image Editor")
            return {'CANCELLED'}

    def calculate_grid(self, context):
        grid_data = {}
        imgs = [x for x in bpy.data.images if x.type != 'RENDER_RESULT']
        
        viewport_width = context.region.width
        viewport_height = context.region.height
        
        # Dynamically update columns on the fly
        self.columns = max(1, int(viewport_width // (self.cell_size + self.spacing)))
        
        active_image = self.edarea.spaces.active.image
        active_idx = imgs.index(active_image) if active_image in imgs else 0
        
        rows = math.ceil(len(imgs) / self.columns) if self.columns > 0 else 1
        total_height = rows * (self.cell_size + self.spacing)
        
        # Center the view on the currently viewed image on initial launch / zoom
        if not ImageGalleryOverlay._initialized:
            active_row = active_idx // self.columns
            # Math positions the row comfortably in the middle of the screen
            self.scroll_y = (viewport_height * 0.5) - (active_row * (self.cell_size + self.spacing)) - (self.cell_size / 2.0)
            ImageGalleryOverlay._initialized = True

        # Clamp scrolling bounds natively
        if total_height > viewport_height:
            self.scroll_y = max(viewport_height - total_height, min(self.scroll_y, 0))
        else:
            self.scroll_y = 0
            
        # Vectorize bounding box generation
        for i, image in enumerate(imgs):
            col = i % self.columns
            row = i // self.columns
            
            x = col * (self.cell_size + self.spacing)
            y = viewport_height - (row + 1) * (self.cell_size + self.spacing) + self.scroll_y
            
            grid_data[image.name] = (x, y, self.cell_size, self.cell_size)
            
        return grid_data

    def draw_callback_px(self, cell_size, spacing, grid_data):
        shader = gpu.shader.from_builtin('IMAGE')
        
        viewport_width = bpy.context.region.width
        viewport_height = bpy.context.region.height
        
        for image_name, rect in grid_data.items():
            x, y, w, h = rect
            
            # Strict early exit to skip out-of-frame images completely
            if y + h < 0 or y > viewport_height or x + w < 0 or x > viewport_width:
                continue
                
            image = bpy.data.images[image_name]
            img_w, img_h = image.size
            
            if img_w > 0 and img_h > 0:
                # Calculate largest fitting aspect ratio within the hardcoded square cell
                ratio = min(w / img_w, h / img_h)
                draw_w = img_w * ratio
                draw_h = img_h * ratio
                
                # Center inside cell with offsets
                offset_x = (w - draw_w) / 2.0
                offset_y = (h - draw_h) / 2.0
                
                px = x + offset_x
                py = y + offset_y
                
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
    bpy.utils.unregister_class(ImageGalleryOverlay)
    bpy.types.IMAGE_MT_view.remove(menu_func)

if __name__ == "__main__":
    register()