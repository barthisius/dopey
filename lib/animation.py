# This file is part of MyPaint.
# Copyright (C) 2007-2008 by Martin Renold <martinxyz@gmx.ch>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os
import glob
from gettext import gettext as _
from layer import PaintingLayer
import json
import tempfile
from subprocess import call

import pixbufsurface

import anicommand
from timeline import TimeLine
from xdna import XDNA
from mypaintlib import combine_mode_get_info
from tiledsurface import OPENRASTER_COMBINE_MODES
from tiledsurface import DEFAULT_COMBINE_MODE


class Animation(object):
    
    opacities = {
    'cel':   0.5,
    'key':        0.4,
    'inbetweens': 0.2,
    'other keys': 0.3,
    'other':      0,
    }
    
    def __init__(self, doc):
        self.doc = doc
        self.timeline = None
        self.cleared = False
        self.using_legacy = False
        self.xdna = XDNA()

        # For reproduction, "play", "pause", "stop":
        self.player_state = None

        # For cut/copy/paste operations:
        self.edit_operation = None
        self.edit_frame = None

    def clear_xsheet(self, init=False):
        self.timeline = TimeLine(self.opacities)
        self.timeline.append_layer()
        self.cleared = True
    
    def legacy_xsheet_as_str(self):
        """
        Return animation X-Sheet as data in json format.
        (only saves first layer! (if it works? i dont even know. it should))

        """
        data = []
        for nf in self.timeline.layer:
            f = self.timeline.layer[nf]
            if f.cel is not None:
                layer_idx = self.doc.layers.index(f.cel)
            else:
                layer_idx = None
            data.append((f.is_key, f.description, layer_idx))
        str_data = json.dumps(data, sort_keys=True, indent=4)
        return str_data

    def rev1_xsheet_as_str(self):
        """
        Return animation X-Sheet as data in XDNA format.

        """
        x = self.xdna

        data = {
            'metadata': x.application_signature,
            'XDNA': x.xdna_signature,
            'xsheet': {
                'framerate': self.timeline.fps,
                'raster_frame_lists': []
            }
        }

        for l, layer in enumerate(self.timeline):
            data['xsheet']['raster_frame_lists'].append([])
            for nf in range(len(layer)):
                if nf in layer:
                    f = layer[nf]
                    if f.cel is not None:
                        layer_idx = self.doc.layers.index(f.cel)
                    else:
                        layer_idx = None
                    data['xsheet']['raster_frame_lists'][l].append({
                        'idx': layer_idx,
                        'is_key': f.is_key,
                        'description': f.description
                    })
                else:
                    data['xsheet']['raster_frame_lists'][l].append({
                        'idx': None,
                        'is_key': False,
                        'description': ''
                    })

        str_data = json.dumps(data, sort_keys=True, indent=4)
        return str_data

    def xsheet_as_str(self):
        """
        Return animation X-Sheet as data in newer XDNA format.

        """
        x = self.xdna

        data = {
            'metadata': x.application_signature,
            'XDNA': x.xdna_signature,
            'xsheet': {
                'framerate': self.timeline.fps,
                'raster_frame_lists': []
            }
        }

        self.timeline.cleanup()
        for l, layer in enumerate(self.timeline):
            compop = combine_mode_get_info(layer.composite).get("name", '')
            data['xsheet']['raster_frame_lists'].append({
                'description': layer.description,
                'visible': layer.visible,
                'opacity': layer.opacity,
                'locked': layer.locked,
                'composite': compop,
                'frames': {}
            })
            for nf in layer:
                f = layer[nf]
                if f.cel is not None:
                    layer_path = self.doc.layer_stack.deepindex(f.cel)
                else:
                    layer_path = None
                data['xsheet']['raster_frame_lists'][l]['frames'][nf] = {
                    'path': layer_path,
                    'is_key': f.is_key,
                    'description': f.description
                }

        str_data = json.dumps(data, sort_keys=True, indent=4)
        return str_data

    def _write_xsheet(self, xsheetfile):
        """
        Save FrameList to file.
        
        """
        str_data = self.xsheet_as_str()
        xsheetfile.write(str_data)

    def str_to_xsheet(self, ani_data):
        """
        Update TimeLine from animation data.
    
        """
        data = json.loads(ani_data)
        # first check if it's in the legacy non-descriptive JSON or new XDNA format
        if type(data) is dict and data['XDNA']:
            x = self.xdna

            raster_frames = data['xsheet']['raster_frame_lists']

            self.timeline = TimeLine(self.opacities)
            self.timeline.fps = int(data['xsheet']['framerate'])
            self.cleared = True


            #check which version of the XDNA format is being used
            if type(raster_frames[0]) is dict:
                print 'Loading using current file format'
                # load with current format (dictionaries)
                for j in range(len(raster_frames)):
                    self.timeline.append_layer()
                    self.timeline[j].description = str(raster_frames[j]['description'])
                    self.timeline[j].visible = raster_frames[j]['visible']
                    self.timeline[j].opacity = raster_frames[j]['opacity']
                    self.timeline[j].locked = raster_frames[j]['locked']
                    self.timeline[j].composite = OPENRASTER_COMBINE_MODES.get(
                        str(raster_frames[j]['composite']), DEFAULT_COMBINE_MODE)
                    if 'frames' in raster_frames[j]:
                        for i in raster_frames[j]['frames']:
                            d = raster_frames[j]['frames'][i]
                            f = self.timeline[j][int(i)]
                            if d['path'] is not None:
                                cel = self.doc.layer_stack.deepget(d['path'])
                                if cel is None:
                                    cel = PaintingLayer()
                                    self.doc.layer_stack.append(cel)
                            else:
                                cel = None
                            f.is_key = d['is_key']
                            f.description = d['description']
                            f.cel = cel
                    else:		#(temporary) legacy support
                        for ui in raster_frames[j]:
                            try:
                                i = int(ui)
                            except ValueError:
                                continue
                            d = raster_frames[j][ui]
                            f = self.timeline[j][i]
                            if 'path' in d:
                                if d['path'] is not None:
                                    cel = self.doc.layer_stack.deepget(d['path'])
                                    if cel is None:
                                        cel = PaintingLayer()
                                        self.doc.layer_stack.append(cel)
                                else:
                                    cel = None
                            else:
                                if d['idx'] is not None:
                                    cel = self.doc.layer_stack.deepget(
                                          (len(self.doc.layer_stack)-int(d['idx'])-1,))
                                    if cel is None:
                                        cel = PaintingLayer()
                                        self.doc.layer_stack.append(cel)
                                else:
                                    cel = None
                            f.is_key = d['is_key']
                            f.description = str(d['description'])
                            f.cel = cel
                
            else:
                # load with revision 1 format (lists)
                print 'Loading using revision 1 file format'
                for j in range(len(raster_frames)):
                    self.timeline.append_layer()
                    for i, d in enumerate(raster_frames[j]):
                        if d['idx'] is not None:
                            if d['idx'] < len(self.doc.layer_stack):
                                cel = self.doc.layer_stack.deepget(
                                       (len(self.doc.layer_stack)-int(d['idx'])-1,))
                            else:
                                cel = PaintingLayer()
                                self.doc.layer_stack.append(cel)
                        else:
                            cel = None
                        self.timeline[j][i].is_key = d['is_key']
                        self.timeline[j][i].description = d['description']
                        self.timeline[j][i].cel = cel
                self.timeline.cleanup()

        else:
            # load in legacy non-descriptive JSON style
            print 'Loading using legacy file format'
            self.using_legacy = True
            self.timeline = TimeLine(self.opacities)
            self.timeline.append_layer()
            self.cleared = True
            for i, d in enumerate(data):
                is_key, description, layer_idx = d
                if layer_idx is not None:
                    if layer_idx < len(self.doc.layer_stack):
                        cel = self.doc.layer_stack.deepget(
                                 (len(self.doc.layer_stack)-int(d['idx'])-1,))
                    else:
                        cel = PaintingLayer()
                        self.doc.layer_stack.append(cel)
                else:
                    cel = None
                self.timeline[0][i].is_key = is_key
                self.timeline[0][i].description = description
                self.timeline[0][i].cel = cel
            self.timeline.cleanup()

    def _read_xsheet(self, xsheetfile):
        """
        Update FrameList from file.
    
        """
        ani_data = xsheetfile.read()
        self.str_to_xsheet(ani_data)
    
    def save_xsheet(self, filename):
        root, ext = os.path.splitext(filename)
        xsheet_fn = root + '.xsheet'
        xsheetfile = open(xsheet_fn, 'w')
        self._write_xsheet(xsheetfile)
    
    def load_xsheet(self, filename):
        root, ext = os.path.splitext(filename)
        xsheet_fn = root + '.xsheet'
        try:
            xsheetfile = open(xsheet_fn, 'r')
        except IOError:
            self.clear_xsheet()
        else:
            self._read_xsheet(xsheetfile)
    
    def save_png(self, filename, **kwargs):
        prefix, ext = os.path.splitext(filename)
        # if we have a number already, strip it
        l = prefix.rsplit('-', 1)
        if l[-1].isdigit():
            prefix = l[0]
        doc_bbox = self.doc.get_effective_bbox()

        for i in range(self.timeline.get_first(), self.timeline.get_last()+1):
            frame = PaintingLayer()
            for j in range(len(self.timeline)):
                cel = self.timeline[j].cel_at(i)
                visible, opacity = cel.visible, cel.opacity
                cel.visible, cel.opacity = True, self.timeline[j].opacity
                cel.merge_into(frame)
                cel.visible, cel.opacity = visible, opacity
            filename = '%s-%03d%s' % (prefix, i+1, ext)
            frame._surface.save_as_png(filename, *doc_bbox, **kwargs)

    def save_gif(self, filename, gif_fps=24, gif_loop=0, **kwargs):
        # Requires command tool imagemagick.
        tempdir = tempfile.mkdtemp()
        gifs_tempdir = os.path.join(tempdir, 'gifs')
        os.mkdir(gifs_tempdir)
        base_filename = os.path.basename(filename)
        prefix, ext = os.path.splitext(base_filename)
        out_filename = os.path.join(os.path.dirname(filename), prefix + '.gif')

        pngs_filename = os.path.join(tempdir, 'tempani.png')
        self.save_png(pngs_filename)

        # convert pngs to jpegs with imagemagick command:
        pngs_list = glob.glob(tempdir + os.path.sep + '*png')
        pngs_list.sort()
        for png_file in pngs_list:
            f_basename = os.path.basename(png_file)
            name, ext = os.path.splitext(f_basename)
            gif_file = os.path.join(gifs_tempdir, name + '.gif')
            print "converting %s to %s..." % (png_file, gif_file)
            call(["convert",
                  "-background", "white",
                  "-flatten",
                  png_file, gif_file])

        # convert the previous gifs to animated gif with imagemagick command:
        gifs = gifs_tempdir + os.path.sep + 'tempani-*.gif'
	gif_filename = os.path.join(tempdir, 'temp.gif')
        call(["convert",
              "-delay", "1x" + str(gif_fps),
              "-loop", str(gif_loop),
              gifs, gif_filename])

        # optimize gif size:
        call(["convert",
              "-layers", "Optimize",
              gif_filename, out_filename])

    def save_avi(self, filename, vid_width=800, vid_fps=24, **kwargs):
        """
        Save video file with codec mpeg4.

        Requires command tools imagemagick and ffmpeg .

        """
        tempdir = tempfile.mkdtemp()
        jpgs_tempdir = os.path.join(tempdir, 'jpgs')
        os.mkdir(jpgs_tempdir)
        base_filename = os.path.basename(filename)
        prefix, ext = os.path.splitext(base_filename)
        out_filename = os.path.join(os.path.dirname(filename), prefix + '.avi')

        pngs_filename = os.path.join(tempdir, 'tempani.png')
        self.save_png(pngs_filename)

        # convert pngs to jpegs with imagemagick command:
        pngs_list = glob.glob(tempdir + os.path.sep + '*png')
        pngs_list.sort()
        for png_file in pngs_list:
            f_basename = os.path.basename(png_file)
            name, ext = os.path.splitext(f_basename)
            jpg_file = os.path.join(jpgs_tempdir, name + '.jpg')
            print "converting %s to %s..." % (png_file, jpg_file)
            call(["convert",
                  "-resize", str(vid_width),
                  "-quality", "100",
                  "-background", "white",
                  "-flatten",
                  png_file, jpg_file])

        # convert the previous jpgs to video with ffmpeg command:
        jpgs = jpgs_tempdir + os.path.sep + 'tempani-%03d.jpg'
        call(["ffmpeg",
              "-r", str(vid_fps),
              "-b", "1800",
              "-y", "-i",
              jpgs, out_filename])

    def hide_all_frames(self):
        for cel in self.timeline.get_all_cels():
            cel.visible = False

    def change_visible_frame(self, prev_idx, cur_idx):
        prev_cels = self.timeline.cels_at(prev_idx)
        cur_cels = self.timeline.cels_at(cur_idx)
        if prev_cels == cur_cels: return
        for cel in prev_cels:
            if cel in cur_cels:
                continue
            if cel != None:
                cel.visible = False
        for cel in cur_cels:
            if cel in prev_cels:
                continue
            if cel != None:
                cel.opacity = 1
                cel.visible = True

    def update_opacities(self):
        opacities, visible = self.timeline.get_opacities()

        for cel, opa in opacities.items():
            if cel is None:
                continue
            cel.opacity = opa

        for cel, vis in visible.items():
            if cel is None:
                continue
            cel.visible = vis

    def generate_layername(self, idx, l_idx, description):
        letter = ""
        try:
            digits = int(math.log(l_idx, 26) + 1)
        except:
            digits = 1
        for i in range(digits)[::-1]:
            n = l_idx // (26 ** i)
            if i == 0: n += 1
            letter += chr(n+64)
            l_idx -= (26 ** i) * n
        layername = "<" + letter + "> CEL " + str(idx + 1)
        if description != '':
            layername += ": " + description
        return layername

    def select_without_undo(self, idx):
        """Like the command but without undo/redo."""
        self.timeline.select(idx)
        self.update_opacities()

    def play_animation(self):
        self.player_state = "play"
        self.doc.call_doc_observers()

    def pause_animation(self):
        self.player_state = "pause"

    def playpause_animation(self):
        if self.player_state != "play":
            self.player_state = "play"
        else:
            self.player_state = "pause"
        self.doc.call_doc_observers()

    def stop_animation(self):
        self.player_state = "stop"

    def player_next(self, use_lightbox=False):
        prev_idx = self.timeline.idx
        if self.timeline.has_next():
            self.timeline.goto_next()
        else:
            self.timeline.select(self.timeline.get_first())
        if use_lightbox:
            self.update_opacities()
        else:
            self.change_visible_frame(prev_idx, self.timeline.idx)

    def toggle_key(self, lidx=None, idx=None):
        if lidx is None:
            lidx = self.timeline.layer_idx
        if idx is None:
            idx = self.timeline.idx
        if idx not in self.timeline[lidx]:
            self.doc.do(anicommand.AddFrame(self.doc, lidx, idx, True))
        frame = self.timeline[lidx][idx]
        self.doc.do(anicommand.ToggleKey(self.doc, frame))

    def toggle_skip_visible(self):
        if lidx is None:
            lidx = self.timeline.layer_idx
        if idx is None:
            idx = self.timeline.idx
        if idx not in self.timeline[lidx]:
            self.doc.do(anicommand.AddFrame(self.doc, lidx, idx, True))
        frame = self.timeline[lidx][idx]
        self.doc.do(anicommand.ToggleSkipVisible(self.doc, frame))

    def previous_frame(self, with_cel=False):
        if self.timeline.idx == 0: return
        self.select(self.timeline.idx - 1)

    def next_frame(self, with_cel=False):
        self.select(self.timeline.idx + 1)

    def previous_keyframe(self):
        new = self.timeline.goto_previous_key()
        cel = self.timeline.layer.cel_at(self.timeline.idx)
        if cel is not None:
            layer_idx = self.doc.layers.index(cel)
            self.doc.layer_idx = layer_idx
        self.update_opacities()
        if new: self.cleared = True
        self.doc.call_doc_observers()

    def next_keyframe(self):
        new = self.timeline.goto_next_key()
        cel = self.timeline.layer.cel_at(self.timeline.idx)
        if cel is not None:
            layer_idx = self.doc.layers.index(cel)
            self.doc.layer_idx = layer_idx
        self.update_opacities()
        if new: self.cleared = True
        self.doc.call_doc_observers()
    
    def change_description(self, new_description, frame=None):
        if frame is None: frame = self.timeline.get_selected()
        self.doc.do(anicommand.ChangeDescription(self.doc, frame, self.timeline.layer_idx, self.timeline.idx, new_description))
    
    def add_cel(self, layer=None, frame=None):
        if layer is None: layer = self.timeline.layer_idx
        if frame is None: frame = self.timeline.idx
        if self.timeline[layer][frame].cel is not None:
            return
        self.doc.do(anicommand.AddFrame(self.doc, layer, frame))

    def remove_frame(self, layer=None, frame=None):
        if layer is None: layer = self.timeline.layer_idx
        if frame is None: frame = self.timeline.idx
        self.doc.do(anicommand.RemoveFrame(self.doc, frame, layer))

    def move_frame(self, frame, amount):	#@TODO: add to undo stack
        self.timeline.layer.insert(frame+amount,self.timeline.layer.pop(frame))
        self.sort_layers()
        self.doc.call_doc_observers()

    def move_layer(self, layer, amount):	#@TODO: add to undo stack
        self.timeline.insert_layer(layer+amount,self.timeline.pop(layer))
        self.sort_layers()
        self.doc.call_doc_observers()

    def select(self, idx):
        if self.timeline.idx != idx:
            self.doc.do(anicommand.SelectFrame(self.doc, idx))

    def select_layer(self, idx):
        if self.timeline.layer_idx != idx:
            self.doc.do(anicommand.SelectAnimationLayer(self.doc, idx))

    def previous_layer(self):
        self.select_layer(self.timeline.layer_idx - 1)

    def next_layer(self):
        self.select_layer(self.timeline.layer_idx + 1)

    def add_layer(self, idx=None):
        self.doc.do(anicommand.InsertLayer(self.doc, idx))

    def remove_layer(self, idx=None):
        self.doc.do(anicommand.RemoveLayer(self.doc, idx))

    def set_layer_opacity(self, opac):		#@TODO: add to command stack
        self.timeline.layer.opacity = opac
        self.update_opacities()

    def set_layer_composite(self, comp):	#@TODO: add to command stack
        self.timeline.layer.composite = comp
        for frame in self.timeline.layer:
            f = self.timeline.layer[frame]
            if f.cel:
                f.cel.compositeop = comp
        self.doc.call_doc_observers()

    def sort_layers(self):
        #@TODO: temporary implimentation using restack command (murders command stack)
        import command
        layers = self.doc.layer_stack
        new_order = self.timeline.get_order(layers)
        selection = self.doc.layer_stack.current
        if selection not in new_order: return
        rename = False
        for nl, l in enumerate(new_order):
            src_path = layers.deepindex(l)
            tar_path = (nl,)
            if src_path != tar_path:
                rename = True
                self.doc.do(command.RestackLayer(self.doc, src_path, tar_path))
        layers.set_current_path(layers.canonpath(path=layers.deepindex(selection)))
        if rename: self.rename_layers()

    def rename_layers(self):
        for l, layer in enumerate(self.timeline):
            for f in layer:
                if layer[f].has_cel():
                    new_name = self.generate_layername(f, l, layer[f].description)
                    layer[f].cel.name = new_name


    def change_opacityfactor(self, opacityfactor):
        self.timeline.set_opacityfactor(opacityfactor)
        self.update_opacities()

    def toggle_opacity(self, attr, is_active):
        self.timeline.setup_active_cels({attr: is_active})
        self.update_opacities()
    
    def toggle_nextprev(self, nextprev, is_active):
        self.timeline.setup_nextprev({nextprev: is_active})
        self.update_opacities()
    
    def can_cutcopy(self):
        if self.timeline.idx not in self.timeline.layer: return False
        frame = self.timeline.get_selected()
        return frame.cel is not None

    def cutcopy_cel(self, edit_operation):
        frame = self.timeline.get_selected()
        self.doc.ani.edit_operation = edit_operation
        self.doc.ani.edit_frame = frame
        self.doc.call_doc_observers()

    def can_paste(self):
        if self.edit_frame is None: return False
        if self.timeline.idx not in self.timeline.layer: return True
        frame = self.timeline.get_selected()
        return self.edit_frame != frame and \
               frame.cel == None

    def paste_cel(self):
        frame = self.timeline.get_selected()
        self.doc.do(anicommand.PasteCel(self.doc, frame))
