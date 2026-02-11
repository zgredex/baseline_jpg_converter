#!/usr/bin/env python
# -*- coding: utf-8 -*-

from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import error_dialog, info_dialog
from qt.core import QProgressDialog, Qt

class BaselineJPGAction(InterfaceAction):
    name = 'Baseline JPEG Converter'
    action_spec = ('Baseline JPEG Converter', None, 'Convert covers and EPUB images to baseline JPEG', None)
    action_type = 'current'
    
    def genesis(self):
        self.qaction.triggered.connect(self.convert_covers)
        
    def convert_covers(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows:
            error_dialog(self.gui, 'No Selection', 
                        'Please select one or more books first.', show=True)
            return
        
        book_ids = list(map(self.gui.library_view.model().id, rows))
        self.do_convert(book_ids)
    
    def convert_image_to_baseline(self, image_data):
        from PIL import Image
        from io import BytesIO
        
        try:
            img = Image.open(BytesIO(image_data))
            
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    background.paste(img, mask=img.split()[-1])
                    img = background
                else:
                    img = img.convert('RGB')
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            output = BytesIO()
            img.save(output, format='JPEG', quality=85, progressive=False, optimize=False)
            return output.getvalue()
        except Exception:
            return None
    
    def fix_svg_cover(self, xhtml_content, xhtml_path):
        """
        Fix SVG-based cover pages that don't render on some e-readers.
        Replaces SVG with xlink:href with a simple img tag.
        Returns (fixed_content, was_fixed).
        """
        import re
        
        # Check if this is a cover page with SVG
        if '<svg' not in xhtml_content or 'xlink:href' not in xhtml_content:
            return xhtml_content, False
        
        # Check for cover indicators
        is_cover = (
            'calibre:cover' in xhtml_content or
            'name="cover"' in xhtml_content or
            '<title>Cover</title>' in xhtml_content
        )
        if not is_cover:
            return xhtml_content, False
        
        # Extract image path from SVG xlink:href
        match = re.search(r'xlink:href=["\']([^"\']+)["\']', xhtml_content)
        if not match:
            return xhtml_content, False
        
        image_path = match.group(1)  # Keep original relative path!
        
        # Build replacement HTML with epub:type="cover" for compatibility
        new_xhtml = '''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>

<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">
<head>
  <meta content="text/html; charset=UTF-8" http-equiv="default-style"/>
  <title>Cover</title>
</head>

<body>
  <section epub:type="cover">
    <img alt="Cover" src="''' + image_path + '''"/>
  </section>
</body>
</html>'''
        
        return new_xhtml, True
    
    def ensure_cover_meta(self, opf_content):
        """
        Ensure OPF has <meta name="cover" content="X"/> pointing to cover image.
        This is required by many e-readers including CrossPoint.
        Returns (modified_content, was_modified).
        """
        import re
        
        # Check if already has cover meta
        if '<meta name="cover"' in opf_content:
            return opf_content, False
        
        # Find cover image id from manifest (look for cover-image property or cover in id/href)
        cover_id = None
        
        # First try: find item with properties="cover-image"
        match = re.search(r'<item[^>]+id="([^"]+)"[^>]+properties="[^"]*cover-image[^"]*"', opf_content)
        if match:
            cover_id = match.group(1)
        
        # Second try: find item with properties before id
        if not cover_id:
            match = re.search(r'<item[^>]+properties="[^"]*cover-image[^"]*"[^>]+id="([^"]+)"', opf_content)
            if match:
                cover_id = match.group(1)
        
        # Third try: find item with "cover" in id and image media-type
        if not cover_id:
            match = re.search(r'<item[^>]+id="([^"]*cover[^"]*)"[^>]+media-type="image/', opf_content, re.IGNORECASE)
            if match:
                cover_id = match.group(1)
        
        if not cover_id:
            return opf_content, False
        
        # Add meta tag before </metadata>
        new_meta = f'    <meta name="cover" content="{cover_id}"/>\n  </metadata>'
        opf_content = opf_content.replace('</metadata>', new_meta)
        
        return opf_content, True
    
    def convert_epub_images(self, epub_path):
        import zipfile
        import tempfile
        import os
        import shutil
        import re
        
        converted_count = 0
        svg_covers_fixed = 0
        cover_meta_added = False
        renamed_files = {}
        
        temp_fd, temp_path = tempfile.mkstemp(suffix='.epub')
        os.close(temp_fd)
        
        try:
            with zipfile.ZipFile(epub_path, 'r') as zin:
                for item in zin.infolist():
                    lower_name = item.filename.lower()
                    if lower_name.endswith(('.png', '.gif', '.webp', '.bmp')):
                        base_name = item.filename.rsplit('.', 1)[0]
                        new_name = base_name + '.jpg'
                        renamed_files[item.filename] = new_name
                
                with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as zout:
                    for item in zin.infolist():
                        data = zin.read(item.filename)
                        filename = item.filename
                        lower_name = filename.lower()
                        
                        if lower_name.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')):
                            new_data = self.convert_image_to_baseline(data)
                            if new_data:
                                data = new_data
                                converted_count += 1
                                if filename in renamed_files:
                                    filename = renamed_files[filename]
                        
                        elif lower_name.endswith(('.xhtml', '.html', '.htm')):
                            try:
                                text = data.decode('utf-8')
                                
                                # Fix SVG covers
                                text, was_fixed = self.fix_svg_cover(text, filename)
                                if was_fixed:
                                    svg_covers_fixed += 1
                                
                                # Update image references for renamed files
                                for old_name, new_name in renamed_files.items():
                                    old_basename = old_name.split('/')[-1]
                                    new_basename = new_name.split('/')[-1]
                                    text = text.replace(old_basename, new_basename)
                                    text = text.replace(old_name, new_name)
                                data = text.encode('utf-8')
                            except Exception:
                                pass
                        
                        elif lower_name.endswith('.css'):
                            try:
                                text = data.decode('utf-8')
                                for old_name, new_name in renamed_files.items():
                                    old_basename = old_name.split('/')[-1]
                                    new_basename = new_name.split('/')[-1]
                                    text = text.replace(old_basename, new_basename)
                                    text = text.replace(old_name, new_name)
                                data = text.encode('utf-8')
                            except Exception:
                                pass
                        
                        elif lower_name.endswith('.ncx'):
                            try:
                                text = data.decode('utf-8')
                                for old_name, new_name in renamed_files.items():
                                    old_basename = old_name.split('/')[-1]
                                    new_basename = new_name.split('/')[-1]
                                    text = text.replace(old_basename, new_basename)
                                    text = text.replace(old_name, new_name)
                                data = text.encode('utf-8')
                            except Exception:
                                pass
                        
                        elif lower_name.endswith('.opf'):
                            try:
                                text = data.decode('utf-8')
                                
                                # Update image references
                                for old_name, new_name in renamed_files.items():
                                    old_basename = old_name.split('/')[-1]
                                    new_basename = new_name.split('/')[-1]
                                    text = text.replace(old_basename, new_basename)
                                    text = text.replace(old_name, new_name)
                                
                                # Fix media-types for renamed images
                                text = re.sub(
                                    r'href="([^"]+\.jpg)"([^>]*)media-type="image/(png|gif|webp|bmp)"',
                                    r'href="\1"\2media-type="image/jpeg"',
                                    text
                                )
                                text = re.sub(
                                    r'media-type="image/(png|gif|webp|bmp)"([^>]*)href="([^"]+\.jpg)"',
                                    r'media-type="image/jpeg"\2href="\3"',
                                    text
                                )
                                
                                # Remove svg from properties if we fixed the cover
                                if svg_covers_fixed > 0:
                                    text = re.sub(r'\s+svg(?=["\s>])', '', text)
                                    text = text.replace('properties=" "', '')
                                    text = text.replace("properties=' '", '')
                                
                                # Ensure cover meta exists
                                text, meta_added = self.ensure_cover_meta(text)
                                if meta_added:
                                    cover_meta_added = True
                                
                                data = text.encode('utf-8')
                            except Exception:
                                pass
                        
                        if item.filename == 'mimetype':
                            zout.writestr(item, data, compress_type=zipfile.ZIP_STORED)
                        else:
                            new_info = zipfile.ZipInfo(filename)
                            new_info.compress_type = zipfile.ZIP_DEFLATED
                            zout.writestr(new_info, data)
            
            shutil.move(temp_path, epub_path)
            
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise e
        
        return converted_count, svg_covers_fixed, cover_meta_added
    
    def do_convert(self, book_ids):
        from PIL import Image
        from io import BytesIO
        import os
        
        db = self.gui.current_db.new_api
        converted_covers = 0
        converted_epub_images = 0
        svg_covers_fixed = 0
        cover_metas_added = 0
        errors = []
        
        progress = QProgressDialog('Converting images...', 'Cancel', 0, len(book_ids), self.gui)
        progress.setWindowModality(Qt.WindowModal)
        progress.setWindowTitle('Converting to Baseline JPEG')
        
        for i, book_id in enumerate(book_ids):
            if progress.wasCanceled():
                break
                
            progress.setValue(i)
            title = db.field_for('title', book_id)
            progress.setLabelText(f'Processing: {title}\n({i+1} of {len(book_ids)})')
            
            try:
                cover_data = db.cover(book_id)
                if cover_data:
                    img = Image.open(BytesIO(cover_data))
                    
                    if img.mode in ('RGBA', 'LA', 'P'):
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        if img.mode in ('RGBA', 'LA'):
                            background.paste(img, mask=img.split()[-1])
                            img = background
                        else:
                            img = img.convert('RGB')
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    output = BytesIO()
                    img.save(output, format='JPEG', quality=85, progressive=False, optimize=False)
                    new_data = output.getvalue()
                    
                    db.set_cover({book_id: new_data})
                    converted_covers += 1
            except Exception as e:
                errors.append(f'{title} (cover): {str(e)}')
            
            try:
                formats = db.formats(book_id)
                if formats and 'EPUB' in formats:
                    epub_path = db.format_abspath(book_id, 'EPUB')
                    if epub_path and os.path.exists(epub_path):
                        img_count, svg_count, meta_added = self.convert_epub_images(epub_path)
                        converted_epub_images += img_count
                        svg_covers_fixed += svg_count
                        if meta_added:
                            cover_metas_added += 1
            except Exception as e:
                errors.append(f'{title} (EPUB): {str(e)}')
        
        progress.setValue(len(book_ids))
        
        msg = f'Converted {converted_covers} cover(s) and {converted_epub_images} EPUB image(s) to baseline JPEG.'
        if svg_covers_fixed > 0:
            msg += f'\nFixed {svg_covers_fixed} SVG cover(s).'
        if cover_metas_added > 0:
            msg += f'\nAdded {cover_metas_added} cover meta tag(s).'
        if errors:
            msg += f'\n\nErrors ({len(errors)}):\n' + '\n'.join(errors[:10])
            if len(errors) > 10:
                msg += f'\n... and {len(errors) - 10} more'
        
        info_dialog(self.gui, 'Conversion Complete', msg, show=True)
        
        if converted_covers > 0:
            self.gui.library_view.model().refresh_ids(book_ids)
            self.gui.cover_flow.dataChanged()
            self.gui.tags_view.recount()
