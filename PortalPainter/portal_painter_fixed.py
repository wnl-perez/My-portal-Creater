import os
import math
import shutil
import subprocess
import tkinter as tk
from tkinter import filedialog, colorchooser, simpledialog, messagebox
from PIL import Image, ImageTk, ImageDraw
from collections import deque

# ---------------- Config ----------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VTFCMD_PATH = os.path.join(SCRIPT_DIR, "VTFCmd.exe")  # your working VTFCmd.exe
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "portal_dlc3","pak01_dir","materials","models","weapons","v_models","v_portalgun")

# ---------------- Helpers ----------------
def clamp(v, a, b):
    return max(a, min(v, b))

def flood_fill(img, xy, color, tol=12):
    """Flood fill like MS Paint"""
    px = img.load()
    w, h = img.size
    x0, y0 = xy
    if not (0 <= x0 < w and 0 <= y0 < h):
        return
    orig = px[x0, y0]
    if orig == color:
        return
    def same(a,b): return all(abs(a[i]-b[i])<=tol for i in range(4))
    q = deque()
    q.append((x0, y0))
    while q:
        x, y = q.popleft()
        if not (0<=x<w and 0<=y<h): continue
        if not same(px[x,y], orig): continue
        px[x,y]=color
        q.extend([(x+1,y),(x-1,y),(x,y+1),(x,y-1)])

# ---------------- Main App ----------------
class PortalPainterApp:
    def __init__(self, root):
        self.root = root
        root.title("Portal Gun Painter")

        # ---------------- State ----------------
        self.texture = None
        self.texture_path = None
        self.draw = None
        self.layers = []
        self.selected_layer = None
        self.tool = "brush"
        self.brush_color = (255,0,0,255)
        self.brush_size = 10
        self.zoom = 1.0
        self.min_zoom, self.max_zoom = 0.2,5.0
        self.undo_stack, self.redo_stack = [], []

        # ---------------- UI ----------------
        self.build_ui()
        self.bind_events()

        # ask for base texture on start
        self.ask_open_texture()

    def build_ui(self):
        # toolbar
        top = tk.Frame(self.root)
        top.pack(side="top", fill="x")
        tk.Button(top, text="Open Texture", command=self.open_texture).pack(side="left")
        tk.Button(top, text="Choose Save Folder", command=self.choose_save_folder).pack(side="left")
        tk.Button(top, text="Save PNG", command=self.save_png).pack(side="left")
        tk.Button(top, text="Save & Convert VTF", command=self.save_and_convert).pack(side="left")

        tk.Label(top,text="Tool:").pack(side="left")
        self.tool_var=tk.StringVar(value="brush")
        tk.Radiobutton(top,text="Brush",variable=self.tool_var,value="brush",command=self.set_tool).pack(side="left")
        tk.Radiobutton(top,text="Eraser",variable=self.tool_var,value="eraser",command=self.set_tool).pack(side="left")
        tk.Radiobutton(top,text="Bucket",variable=self.tool_var,value="bucket",command=self.set_tool).pack(side="left")
        tk.Button(top,text="Undo",command=self.undo).pack(side="left",padx=4)
        tk.Button(top,text="Redo",command=self.redo).pack(side="left",padx=4)
        tk.Button(top,text="Import Image",command=self.import_image).pack(side="left",padx=4)
        tk.Button(top,text="Bake Selected Layer",command=self.bake_layer).pack(side="left",padx=4)

        # color & brush
        right = tk.Frame(top)
        right.pack(side="right")
        tk.Button(right,text="Choose Color",command=self.choose_color).pack()
        tk.Label(right,text="Brush Size").pack()
        self.brush_slider=tk.Scale(right,from_=1,to=200,orient="horizontal",command=self.change_brush_size)
        self.brush_slider.set(self.brush_size)
        self.brush_slider.pack()

        # scale/rotate
        tk.Label(right,text="Layer Scale %").pack()
        self.scale_slider=tk.Scale(right,from_=10,to=400,orient="horizontal",command=self.on_transform_change)
        self.scale_slider.set(100)
        self.scale_slider.pack()
        tk.Label(right,text="Layer Rotation").pack()
        self.rotate_slider=tk.Scale(right,from_=-180,to=180,orient="horizontal",command=self.on_transform_change)
        self.rotate_slider.set(0)
        self.rotate_slider.pack()

        # main area
        main=tk.Frame(self.root)
        main.pack(fill="both",expand=True)
        left=tk.Frame(main,width=200)
        left.pack(side="left",fill="y")
        tk.Label(left,text="Layers").pack(anchor="nw")
        self.layer_listbox=tk.Listbox(left,height=20)
        self.layer_listbox.pack(fill="y",expand=True)
        self.layer_listbox.bind("<<ListboxSelect>>",self.on_layer_select)
        btns=tk.Frame(left)
        btns.pack(fill="x")
        tk.Button(btns,text="Remove Layer",command=self.remove_layer).pack(side="left",padx=2)
        tk.Button(btns,text="Rename Layer",command=self.rename_layer).pack(side="left",padx=2)

        # canvas
        canvas_frame=tk.Frame(main)
        canvas_frame.pack(side="right",fill="both",expand=True)
        self.canvas_w,self.canvas_h=1000,700
        self.canvas=tk.Canvas(canvas_frame,width=self.canvas_w,height=self.canvas_h,bg="#222")
        self.canvas.pack(fill="both",expand=True)
        self.canvas_image_id=None

        # status
        self.status=tk.Label(self.root,text="No texture loaded",anchor="w")
        self.status.pack(side="bottom",fill="x")

        self.save_folder=None

    # ---------------- Events ----------------
    def bind_events(self):
        self.canvas.bind("<ButtonPress-1>",self.left_press)
        self.canvas.bind("<B1-Motion>",self.left_drag)
        self.canvas.bind("<ButtonRelease-1>",self.left_release)
        self.canvas.bind("<ButtonPress-3>",self.right_press)
        self.canvas.bind("<B3-Motion>",self.right_drag)
        self.canvas.bind("<ButtonRelease-3>",self.right_release)
        self.canvas.bind("<MouseWheel>",self.mouse_wheel)
        self.root.bind("<Key>",self.on_key)

    # ---------------- Tools ----------------
    def set_tool(self):
        self.tool=self.tool_var.get()
    def change_brush_size(self,v): self.brush_size=int(float(v))
    def choose_color(self):
        c=colorchooser.askcolor()
        if c and c[0]:
            r,g,b=map(int,c[0])
            self.brush_color=(r,g,b,255)

    # ---------------- Open texture ----------------
    def ask_open_texture(self):
        if messagebox.askyesno("Open Texture","Open Portal texture PNG?"):
            self.open_texture()
    def open_texture(self):
        path=filedialog.askopenfilename(title="Open PNG",filetypes=[("PNG","*.png")])
        if not path: return
        img=Image.open(path).convert("RGBA")
        self.texture=img
        self.texture_path=path
        self.draw=ImageDraw.Draw(self.texture)
        self.undo_stack.clear(); self.redo_stack.clear()
        self.push_undo()
        self.zoom=1.0
        self.refresh_canvas()
        self.status.config(text=f"Loaded: {os.path.basename(path)}")

    # ---------------- Canvas ----------------
    def refresh_canvas(self):
        if self.texture is None: return
        display=self.texture.copy()
        for layer in self.layers:
            img=layer["img"]
            s=layer["scale"]
            scaled=img.resize((int(img.width*s),int(img.height*s)),resample=Image.LANCZOS)
            rotated=scaled.rotate(layer["angle"],expand=True)
            tx=int(layer["x"]-rotated.width//2+self.texture.width//2)
            ty=int(layer["y"]-rotated.height//2+self.texture.height//2)
            display.paste(rotated,(tx,ty),rotated)
        disp_w=int(display.width*self.zoom)
        disp_h=int(display.height*self.zoom)
        disp_resized=display.resize((disp_w,disp_h),resample=Image.NEAREST)
        self.display_image=disp_resized
        self.photo=ImageTk.PhotoImage(disp_resized)
        if self.canvas_image_id is None:
            self.canvas_image_id=self.canvas.create_image(0,0,anchor="nw",image=self.photo)
        else: self.canvas.itemconfig(self.canvas_image_id,image=self.photo)
        self.canvas.config(scrollregion=(0,0,disp_w,disp_h))

    def canvas_to_texture(self,cx,cy):
        if self.texture is None: return None,None
        tx=int(cx/self.zoom)
        ty=int(cy/self.zoom)
        tx=clamp(tx,0,self.texture.width-1)
        ty=clamp(ty,0,self.texture.height-1)
        return tx,ty

    # ---------------- Undo/Redo ----------------
    def push_undo(self):
        if self.texture is None: return
        self.undo_stack.append(self.texture.copy())
        if len(self.undo_stack)>40: self.undo_stack.pop(0)
        self.redo_stack.clear()
    def undo(self):
        if not self.undo_stack: return
        self.redo_stack.append(self.texture.copy())
        self.texture=self.undo_stack.pop()
        self.draw=ImageDraw.Draw(self.texture)
        self.refresh_canvas()
    def redo(self):
        if not self.redo_stack: return
        self.push_undo()
        self.texture=self.redo_stack.pop()
        self.draw=ImageDraw.Draw(self.texture)
        self.refresh_canvas()

    # ---------------- Painting ----------------
    def left_press(self,e):
        if self.texture is None: return
        if self.tool=="bucket":
            tx,ty=self.canvas_to_texture(e.x,e.y)
            self.push_undo()
            flood_fill(self.texture,(tx,ty),self.brush_color)
            self.draw=ImageDraw.Draw(self.texture)
            self.refresh_canvas()
            return
        if self.tool in ("brush","eraser"):
            self.push_undo()
            self.last_x,self.last_y=e.x,e.y
    def left_drag(self,e):
        if self.texture is None: return
        if self.tool=="brush":
            x0,y0=self.canvas_to_texture(self.last_x,self.last_y)
            x1,y1=self.canvas_to_texture(e.x,e.y)
            width=max(1,int(self.brush_slider.get()/max(self.zoom,0.0001)))
            self.draw.line([x0,y0,x1,y1],fill=self.brush_color,width=width)
            self.last_x,self.last_y=e.x,e.y
            self.refresh_canvas()
        elif self.tool=="eraser":
            x,y=self.canvas_to_texture(e.x,e.y)
            width=max(1,int(self.brush_slider.get()/max(self.zoom,0.0001)))
            bbox=[x-width//2,y-width//2,x+width//2,y+width//2]
            ImageDraw.Draw(self.texture).ellipse(bbox,fill=(0,0,0,0))
            self.last_x,self.last_y=e.x,e.y
            self.refresh_canvas()
    def left_release(self,e):
        self.last_x,self.last_y=None,None

    # ---------------- Layer ----------------
    def import_image(self):
        path=filedialog.askopenfilename(title="Import PNG",filetypes=[("PNG","*.png"),("All","*.*")])
        if not path: return
        img=Image.open(path).convert("RGBA")
        if self.texture is None:
            self.texture=Image.new("RGBA",(1024,1024),(0,0,0,255))
            self.draw=ImageDraw.Draw(self.texture)
            self.push_undo()
        lx,ly=self.texture.width//2,self.texture.height//2
        layer={"img":img,"x":lx,"y":ly,"angle":0.0,"scale":1.0,"name":os.path.basename(path)}
        self.layers.append(layer)
        self.layer_listbox.insert(tk.END,layer["name"])
        self.layer_listbox.select_clear(0,tk.END)
        self.layer_listbox.select_set(tk.END)
        self.selected_layer=len(self.layers)-1
        self.scale_slider.set(int(layer["scale"]*100))
        self.rotate_slider.set(int(layer["angle"]))
        self.refresh_canvas()
    def on_layer_select(self,e):
        sel=self.layer_listbox.curselection()
        if not sel: self.selected_layer=None; return
        idx=sel[0]; self.selected_layer=idx
        layer=self.layers[idx]
        self.scale_slider.set(int(layer["scale"]*100))
        self.rotate_slider.set(int(layer["angle"]))
    def remove_layer(self):
        sel=self.layer_listbox.curselection()
        if not sel: return
        idx=sel[0]
        self.layer_listbox.delete(idx)
        self.layers.pop(idx)
        self.selected_layer=None
        self.refresh_canvas()
    def rename_layer(self):
        sel=self.layer_listbox.curselection()
        if not sel: return
        idx=sel[0]
        new=simpledialog.askstring("Rename Layer","New name:",initialvalue=self.layers[idx]["name"])
        if new:
            self.layers[idx]["name"]=new
            self.layer_listbox.delete(idx)
            self.layer_listbox.insert(idx,new)
            self.layer_listbox.select_set(idx)
    def on_transform_change(self,_=None):
        if self.selected_layer is None: return
        idx=self.selected_layer
        layer=self.layers[idx]
        layer["scale"]=max(0.01,self.scale_slider.get()/100.0)
        layer["angle"]=float(self.rotate_slider.get())
        self.refresh_canvas()

    # ---------------- Right-click move ----------------
    def right_press(self,e):
        if self.texture is None: return
        tx,ty=self.canvas_to_texture(e.x,e.y)
        found=None
        for i in range(len(self.layers)-1,-1,-1):
            layer=self.layers[i]
            if self.point_in_layer(tx,ty,layer):
                found=i; break
        if found is not None:
            self.selected_layer=found
            self.layer_listbox.select_clear(0,tk.END)
            self.layer_listbox.select_set(found)
            self._drag_info={"start":(e.x,e.y),"layer_start":(self.layers[found]["x"],self.layers[found]["y"])}
        else: self._drag_info=None
    def right_drag(self,e):
        if not hasattr(self,"_drag_info") or self._drag_info is None: return
        dx=int((e.x-self._drag_info["start"][0])/max(self.zoom,0.0001))
        dy=int((e.y-self._drag_info["start"][1])/max(self.zoom,0.0001))
        lx,ly=self._drag_info["layer_start"]
        layer=self.layers[self.selected_layer]
        layer["x"]=lx+dx; layer["y"]=ly+dy
        self.refresh_canvas()
    def right_release(self,e):
        self._drag_info=None
    def point_in_layer(self,tx,ty,layer):
        cx,cy=layer["x"],layer["y"]
        rx,ry=tx-cx,ty-cy
        angle=-math.radians(layer["angle"])
        ux=rx*math.cos(angle)-ry*math.sin(angle)
        uy=rx*math.sin(angle)+ry*math.cos(angle)
        w,h=layer["img"].width*layer["scale"],layer["img"].height*layer["scale"]
        return -w/2<=ux<=w/2 and -h/2<=uy<=h/2

    # ---------------- Bake ----------------
    def bake_layer(self):
        if self.selected_layer is None:
            messagebox.showinfo("Bake","No layer selected.")
            return
        idx=self.selected_layer
        layer=self.layers.pop(idx)
        s=layer["scale"]
        scaled=layer["img"].resize((int(layer["img"].width*s),int(layer["img"].height*s)),resample=Image.LANCZOS)
        rotated=scaled.rotate(layer["angle"],expand=True)
        tx=int(layer["x"]-rotated.width//2+self.texture.width//2)
        ty=int(layer["y"]-rotated.height//2+self.texture.height//2)
        self.push_undo()
        self.texture.paste(rotated,(tx,ty),rotated)
        self.draw=ImageDraw.Draw(self.texture)
        self.layer_listbox.delete(idx)
        self.selected_layer=None
        self.refresh_canvas()
        self.status.config(text="Layer baked.")

    # ---------------- Save & Convert ----------------
    def choose_save_folder(self):
        folder=filedialog.askdirectory(title="Choose save folder")
        if folder: self.save_folder=folder

    def save_png(self):
        if self.texture is None: return None
        final=self.texture.copy()
        for layer in self.layers:
            s=layer["scale"]
            scaled=layer["img"].resize((int(layer["img"].width*s),int(layer["img"].height*s)),resample=Image.LANCZOS)
            rotated=scaled.rotate(layer["angle"],expand=True)
            tx=int(layer["x"]-rotated.width//2+self.texture.width//2)
            ty=int(layer["y"]-rotated.height//2+self.texture.height//2)
            final.paste(rotated,(tx,ty),rotated)
        if getattr(self,"save_folder",None):
            out_path=os.path.join(self.save_folder,"v_portalgun_edited.png")
        else:
            out_path=filedialog.asksaveasfilename(defaultextension=".png",filetypes=[("PNG","*.png")],initialfile="v_portalgun_edited.png")
            if not out_path: return None
        final.save(out_path)
        self.status.config(text=f"Saved PNG: {out_path}")
        return out_path

    def save_and_convert(self):
        out_png=self.save_png()
        if not out_png: return
        # ensure output dir exists
        os.makedirs(OUTPUT_DIR,exist_ok=True)
        vtf_out=os.path.join(OUTPUT_DIR,"v_portalgun_edited.vtf")
        try:
            subprocess.run([VTFCMD_PATH,"-file",out_png,"-output",vtf_out],check=True)
            self.status.config(text=f"Saved & converted VTF: {vtf_out}")
        except Exception as e:
            messagebox.showerror("Error",f"Failed VTF conversion: {e}")

    # ---------------- Zoom ----------------
    def mouse_wheel(self,e):
        factor=1.1 if e.delta>0 else 0.9
        self.zoom=clamp(self.zoom*factor,self.min_zoom,self.max_zoom)
        self.refresh_canvas()

    # ---------------- Keyboard ----------------
    def on_key(self,e):
        if e.char=="z": self.undo()
        elif e.char=="y": self.redo()

# ---------------- Run ----------------
def main():
    root=tk.Tk()
    root.geometry("1200x800")
    app=PortalPainterApp(root)
    root.mainloop()

if __name__=="__main__":
    main()

