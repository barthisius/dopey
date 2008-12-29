# This file is part of MyPaint.
# Copyright (C) 2008 by Martin Renold <martinxyz@gmx.ch>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY. See the COPYING file for more details.

import gtk, os
gdk = gtk.gdk
import tileddrawwidget, pixbuflist
from lib import tiledsurface, document

class Window(gtk.Window):
    def __init__(self, app):
        gtk.Window.__init__(self)
        self.app = app
        self.add_accel_group(self.app.accel_group)

        self.app.default_background = (255, 255, 255)

        self.set_title('Background')
        self.connect('delete-event', self.app.hide_window_cb)

        vbox = gtk.VBox()
        self.add(vbox)

        nb = gtk.Notebook()
        vbox.pack_start(nb)

        self.bgl = BackgroundList(self)
        nb.append_page(self.bgl, gtk.Label('Pattern'))

        self.cs = gtk.ColorSelection()
        self.cs.connect('color-changed', self.color_changed_cb)
        nb.append_page(self.cs, gtk.Label('Color'))

        hbox = gtk.HBox()
        vbox.pack_start(hbox, expand=False)

        b = gtk.Button('save as default')
        b.connect('clicked', self.save_as_default_cb)
        hbox.pack_start(b)

    def color_changed_cb(self, widget):
        rgb = self.cs.get_current_color()
        rgb = rgb.red, rgb.green, rgb.blue
        rgb = [int(x / 65535.0 * 255.0) for x in rgb] 
        self.set_background(rgb)

    def save_as_default_cb(self, widget):
        pixbuf = self.app.drawWindow.doc.get_background_pixbuf()
        pixbuf.save(os.path.join(self.app.confpath, 'backgrounds', 'default.png'), 'png')
        self.set_background(pixbuf)

    def set_background(self, obj):
        doc = self.app.drawWindow.doc
        doc.set_background(obj)
        self.app.background = obj


class BackgroundObject:
    pass


class BackgroundList(pixbuflist.PixbufList):
    def __init__(self, win):
        self.app = win.app
        self.win = win

        stock_path = os.path.join(self.app.datapath, 'backgrounds')
        user_path  = os.path.join(self.app.confpath, 'backgrounds')
        if not os.path.isdir(user_path):
            os.mkdir(user_path)
        self.backgrounds = []

        def listdir(path):
            l = [os.path.join(path, filename) for filename in os.listdir(path)]
            l.sort()
            return l

        for filename in listdir(user_path) + listdir(stock_path):
            if not filename.lower().endswith('.png'):
                continue
            obj = BackgroundObject()
            obj.pixbuf = gdk.pixbuf_new_from_file(filename)

            # error checking
            def error(msg):
                d = gtk.MessageDialog(type = gtk.MESSAGE_WARNING,
                                      buttons = gtk.BUTTONS_OK,
                                      flags = gtk.DIALOG_MODAL)
                d.set_title('Bad Background Pattern')
                d.set_markup(msg)
                d.run()
                d.destroy()
            if obj.pixbuf.get_has_alpha():
                error('The background %s was ignored because it has an alpha channel. Please remove it.' % filename)
                continue
            w, h = obj.pixbuf.get_width(), obj.pixbuf.get_height()
            N = tiledsurface.N
            if w != N or h != N:
                error('The background %s was ignored because it has the wrong size. Only %dx%d is supported.' % (filename, N, N))
                continue

            if os.path.basename(filename).lower() == 'default.png':
                self.win.set_background(obj.pixbuf)
                continue

            self.backgrounds.append(obj)

        pixbuflist.PixbufList.__init__(self, self.backgrounds, tiledsurface.N, tiledsurface.N)

    def on_select(self, bg):
        self.win.set_background(bg.pixbuf)