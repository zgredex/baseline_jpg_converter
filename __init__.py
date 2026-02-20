#!/usr/bin/env python
# -*- coding: utf-8 -*-

from calibre.customize import InterfaceActionBase

class BaselineJPGConverterPlugin(InterfaceActionBase):
    name = 'Baseline JPEG Converter'
    description = 'Converts images to baseline JPEG and fixes SVG covers for e-reader compatibility'
    supported_platforms = ['windows', 'osx', 'linux']
    author = 'Megabit'
    version = (1, 8, 0)
    minimum_calibre_version = (5, 0, 0)
    
    actual_plugin = 'calibre_plugins.baseline_jpg_cover.ui:BaselineJPGAction'

    def is_customizable(self):
        return False
