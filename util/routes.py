import os
from aiohttp import web
import folder_paths


# 上传视频路由
async def seedance2_upload_video(request):
    """处理视频文件上传"""
    try:
        reader = await request.multipart()
        
        field = await reader.next()
        if field.name != 'video':
            return web.json_response({
                'success': False,
                'error': 'Invalid field name'
            }, status=400)
        
        filename = field.filename
        if not filename:
            return web.json_response({
                'success': False,
                'error': 'No filename provided'
            }, status=400)
        
        # 上传目录
        upload_dir = folder_paths.get_input_directory()
        os.makedirs(upload_dir, exist_ok=True)
        
        # 保存文件
        file_path = os.path.join(upload_dir, filename)
        with open(file_path, 'wb') as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                f.write(chunk)
        
        return web.json_response({
            'success': True,
            'path': filename,
            'full_path': file_path
        })
        
    except Exception as e:
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500)


# 下载视频路由
async def seedance2_download_video(request):
    """处理视频文件下载"""
    try:
        filename = request.query.get('filename', '')
        if not filename:
            return web.json_response({
                'success': False,
                'error': 'No filename provided'
            }, status=400)
        
        # 安全检查：防止目录遍历
        filename = os.path.basename(filename)
        
        # 文件路径
        upload_dir = folder_paths.get_input_directory()
        file_path = os.path.join(upload_dir, filename)
        
        if not os.path.isfile(file_path):
            return web.json_response({
                'success': False,
                'error': 'File not found'
            }, status=404)
        
        # 返回文件
        return web.FileResponse(file_path, headers={
            'Content-Disposition': f'attachment; filename="{filename}"'
        })
        
    except Exception as e:
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500)


def setup_routes(app):
    """设置路由"""
    app.router.add_post("/seedance2/upload-video", seedance2_upload_video)
    app.router.add_get("/seedance2/download-video", seedance2_download_video)
