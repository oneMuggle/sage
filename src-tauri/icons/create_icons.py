#!/usr/bin/env python3
"""创建 Sage 应用图标 PNG 文件"""
import struct
import zlib

def create_png(width, height, color=(79, 70, 229)):
    """创建简单的纯色PNG"""
    def chunk(chunk_type, data):
        chunk_len = struct.pack('>I', len(data))
        chunk_crc = struct.pack('>I', zlib.crc32(chunk_type + data) & 0xffffffff)
        return chunk_len + chunk_type + data + chunk_crc
    
    # PNG signature
    signature = b'\x89PNG\r\n\x1a\n'
    
    # IHDR chunk
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr = chunk(b'IHDR', ihdr_data)
    
    # IDAT chunk (uncompressed pixel data)
    raw_data = b''
    for y in range(height):
        raw_data += b'\x00'  # filter byte
        for x in range(width):
            raw_data += bytes(color)
    
    compressed = zlib.compress(raw_data, 9)
    idat = chunk(b'IDAT', compressed)
    
    # IEND chunk
    iend = chunk(b'IEND', b'')
    
    return signature + ihdr + idat + iend

if __name__ == '__main__':
    # 创建图标
    sizes = [32, 128, 256]
    for size in sizes:
        png_data = create_png(size, size)
        filename = f'{size}x{size}.png'
        with open(filename, 'wb') as f:
            f.write(png_data)
        print(f'Created {filename}')
