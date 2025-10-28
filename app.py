from flask import Flask, render_template, request, jsonify, send_file
import os
import subprocess
import shutil
from werkzeug.utils import secure_filename
import json
import time
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'output')
INPUT_FOLDER = os.path.join(BASE_DIR, 'input')
ASSETS_FOLDER = os.path.join(BASE_DIR, 'assets')
BLENDER_FOLDER = os.path.join(BASE_DIR, 'Blender')
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'json', 'fbx'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max file size

# Create directories if they don't exist
for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, INPUT_FOLDER, ASSETS_FOLDER]:
    os.makedirs(folder, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Add after app initialization
auth = HTTPBasicAuth()
users = {
    "admin": generate_password_hash("admin")
}

@auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username

# Protect your main routes
@app.route('/')
@auth.login_required
def index():
    return render_template('index.html')

@app.route('/extract-pose', methods=['POST'])
def extract_pose():
    try:
        if 'video' not in request.files:
            return jsonify({'error': 'No video file provided'}), 400
        
        video_file = request.files['video']
        
        if video_file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if video_file and allowed_file(video_file.filename):
            filename = secure_filename(video_file.filename)
            input_video_path = os.path.join(INPUT_FOLDER, filename)
            video_file.save(input_video_path)
            
            print(f"Video saved to: {input_video_path}")
            
            # Use the simple version
            extract_script = os.path.join(BASE_DIR, '_temp_extract_pose.py')
            
            if not os.path.exists(extract_script):
                return jsonify({'error': 'extract_pose_simple.py not found'}), 500
            
            print("Running pose extraction...")
            
            # Run directly with video path as argument
            result = subprocess.run(
                ['python', extract_script, input_video_path],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            print(f"Return code: {result.returncode}")
            print(f"Stdout: {result.stdout}")
            if result.stderr:
                print(f"Stderr: {result.stderr}")
            
            if result.returncode != 0:
                return jsonify({'error': f'Pose extraction failed. Return code: {result.returncode}'}), 500
            
            # Check output
            json_output = os.path.join(OUTPUT_FOLDER, 'pose_data.json')
            if not os.path.exists(json_output):
                return jsonify({'error': 'Output JSON file was not created'}), 500
            
            # Get frame count
            with open(json_output, 'r') as f:
                pose_data = json.load(f)
                frame_count = len(pose_data)
            
            return jsonify({
                'success': True,
                'message': f'Pose extraction completed: {frame_count} frames processed',
                'json_file': 'pose_data.json',
                'frame_count': frame_count
            })
        
        return jsonify({'error': 'Invalid file type'}), 400
    
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Pose extraction timed out'}), 500
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/animate-character', methods=['POST'])
def animate_character():
    """
    Module 2: Apply pose data to Mixamo character using Blender
    Runs auto_oneclick.py via Blender in background mode
    """
    try:
        if 'character_fbx' not in request.files:
            return jsonify({'error': 'Character FBX file required'}), 400
        
        character_fbx = request.files['character_fbx']
        
        if character_fbx.filename == '':
            return jsonify({'error': 'No character file selected'}), 400
        
        if not allowed_file(character_fbx.filename):
            return jsonify({'error': 'Invalid file type. Only FBX supported'}), 400
        
        # Check if pose_data.json exists (from Module 1)
        pose_json_path = os.path.join(OUTPUT_FOLDER, 'pose_data.json')
        if not os.path.exists(pose_json_path):
            return jsonify({'error': 'Pose data not found. Please run Module 1 first.'}), 400
        
        # Save character FBX to assets folder
        character_filename = secure_filename(character_fbx.filename)
        character_path = os.path.join(ASSETS_FOLDER, 'character.fbx')
        character_fbx.save(character_path)
        
        print(f"🎭 Character saved to: {character_path}")
        
        # Check if Blender script exists
        blender_script = os.path.join(BLENDER_FOLDER, 'auto_oneclick.py')
        if not os.path.exists(blender_script):
            return jsonify({'error': 'Blender/auto_oneclick.py not found'}), 500
        
        # Find Blender executable
        blender_exe = find_blender_executable()
        if not blender_exe:
            return jsonify({
                'error': 'Blender not found. Please install Blender 4.x from blender.org'
            }), 500
        
        print(f"🎨 Using Blender: {blender_exe}")
        
        # Verify Blender works by checking version
        try:
            version_check = subprocess.run(
                [blender_exe, '--version'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if version_check.returncode != 0:
                return jsonify({'error': 'Blender executable not working'}), 500
            print(f"✅ Blender version check passed")
        except Exception as e:
            print(f"❌ Blender version check failed: {e}")
            return jsonify({'error': f'Blender executable not working: {e}'}), 500
        
        print("🔄 Running Blender animation pipeline...")
        
        # Run Blender with full path and proper arguments
        result = subprocess.run(
            [
                blender_exe,
                '--background',  # No GUI
                '--python', blender_script
            ],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=600  # 10 minute timeout
        )
        
        if result.returncode != 0:
            print(f"❌ Blender failed with return code: {result.returncode}")
            print(f"Blender stderr: {result.stderr}")
            print(f"Blender stdout: {result.stdout}")
            return jsonify({'error': f'Animation failed: {result.stderr}'}), 500
        
        print(f"✅ Blender completed successfully")
        print(f"Blender output: {result.stdout}")
        
        # Check what files were actually generated
        print("📁 Checking output folder contents:")
        output_files = os.listdir(OUTPUT_FOLDER)
        for file in output_files:
            print(f"   - {file}")
        
        # Look for common output file patterns
        possible_fbx_files = [
            'skinned_animation.fbx',
            'animated_character.fbx', 
            'character_animation.fbx',
            'output.fbx',
            'animation.fbx'
        ]
        
        animated_fbx = None
        for fbx_file in possible_fbx_files:
            potential_path = os.path.join(OUTPUT_FOLDER, fbx_file)
            if os.path.exists(potential_path):
                animated_fbx = fbx_file
                print(f"✅ Found animated FBX: {animated_fbx}")
                break
        
        if not animated_fbx:
            # Try to find any .fbx file in output folder
            for file in output_files:
                if file.endswith('.fbx'):
                    animated_fbx = file
                    print(f"✅ Found FBX file: {animated_fbx}")
                    break
        
        if not animated_fbx:
            return jsonify({'error': 'No animated FBX file was generated. Check Blender script output.'}), 500
        
        # Look for MP4 file
        animated_mp4 = None
        possible_mp4_files = ['anim.mp4', 'animation.mp4', 'output.mp4', 'render.mp4']
        for mp4_file in possible_mp4_files:
            potential_path = os.path.join(OUTPUT_FOLDER, mp4_file)
            if os.path.exists(potential_path):
                animated_mp4 = mp4_file
                print(f"✅ Found MP4: {animated_mp4}")
                break
        
        # If no standard MP4 found, look for any MP4
        if not animated_mp4:
            for file in output_files:
                if file.endswith('.mp4'):
                    animated_mp4 = file
                    print(f"✅ Found MP4 file: {animated_mp4}")
                    break
        
        response_data = {
            'success': True,
            'message': 'Character animation completed successfully',
            'animated_fbx': animated_fbx,
            'character_used': character_filename,
            'output_files': output_files  # For debugging
        }
        
        if animated_mp4:
            response_data['animated_mp4'] = animated_mp4
        
        return jsonify(response_data)
    
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Animation timed out (>10 minutes)'}), 500
    except Exception as e:
        print(f"❌ Error in animate_character: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/download/<filename>')
def download_file(filename):
    """Download generated files from output folder"""
    try:
        # Secure the filename to prevent directory traversal
        filename = secure_filename(filename)
        file_path = os.path.join(OUTPUT_FOLDER, filename)
        
        print(f"📥 Download request for: {filename}")
        print(f"📁 Checking path: {file_path}")
        
        if not os.path.exists(file_path):
            print(f"❌ File not found: {file_path}")
            return jsonify({'error': f'File not found: {filename}'}), 404
        
        if not os.path.isfile(file_path):
            print(f"❌ Not a file: {file_path}")
            return jsonify({'error': f'Not a file: {filename}'}), 400
        
        file_size = os.path.getsize(file_path)
        print(f"✅ File found: {filename} ({file_size} bytes)")
        
        # Send file with proper headers
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )
        
    except Exception as e:
        print(f"❌ Download error: {str(e)}")
        return jsonify({'error': f'Download failed: {str(e)}'}), 500

@app.route('/webcam-capture', methods=['POST'])
def webcam_capture():
    """
    Handle webcam capture and save as video
    """
    try:
        if 'video' not in request.files:
            return jsonify({'error': 'No video data received'}), 400
        
        video_data = request.files['video']
        filename = 'webcam_capture_' + str(int(time.time())) + '.webm'
        video_path = os.path.join(INPUT_FOLDER, filename)
        video_data.save(video_path)
        
        # Convert webm to mp4 using ffmpeg if available
        mp4_filename = filename.replace('.webm', '.mp4')
        mp4_path = os.path.join(INPUT_FOLDER, mp4_filename)
        
        try:
            result = subprocess.run(
                ['ffmpeg', '-i', video_path, '-c:v', 'libx264', '-preset', 'fast', mp4_path],
                capture_output=True,
                timeout=60
            )
            if result.returncode == 0:
                os.remove(video_path)  # Remove webm
                filename = mp4_filename
                print(f"✅ Converted webcam capture to MP4: {mp4_filename}")
            else:
                print(f"⚠️ FFmpeg conversion failed, keeping webm format")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print(f"⚠️ FFmpeg not available or timed out, keeping webm format")
        
        return jsonify({
            'success': True,
            'message': 'Webcam video saved successfully',
            'filename': filename
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def find_blender_executable():
    """Try to find Blender executable in common locations"""
    # Check environment variable first
    blender_path = os.environ.get('BLENDER_PATH')
    if blender_path and os.path.exists(blender_path):
        return blender_path
    
    # Check if 'blender' is in PATH
    if shutil.which('blender'):
        return 'blender'
    
    # Common installation paths
    common_paths = [
        r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender\blender.exe",
        r"C:\Program Files (x86)\Blender Foundation\Blender\blender.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Blender Foundation\Blender\blender.exe"),
    ]
    
    for path in common_paths:
        if os.path.exists(path):
            return path
    
    return None

@app.route('/status')
def status():
    """Check if all required components are available"""
    status_info = {
        'extract_pose_script': os.path.exists(os.path.join(BASE_DIR, 'extract_pose.py')),
        'blender_script': os.path.exists(os.path.join(BLENDER_FOLDER, 'auto_oneclick.py')),
        'blender_executable': find_blender_executable() is not None,
        'output_folder': os.path.exists(OUTPUT_FOLDER),
        'input_folder': os.path.exists(INPUT_FOLDER),
        'assets_folder': os.path.exists(ASSETS_FOLDER),
    }
    return jsonify(status_info)

@app.route('/debug-blender')
def debug_blender():
    blender_exe = find_blender_executable()
    info = {
        'blender_path': blender_exe,
        'path_exists': os.path.exists(blender_exe) if blender_exe else False,
        'is_file': os.path.isfile(blender_exe) if blender_exe else False,
        'blender_script_exists': os.path.exists(os.path.join(BLENDER_FOLDER, 'auto_oneclick.py'))
    }
    
    # Test if Blender runs
    if blender_exe and os.path.exists(blender_exe):
        try:
            test = subprocess.run([blender_exe, '--version'], capture_output=True, text=True, timeout=10)
            info['version_test'] = test.returncode == 0
            info['version_output'] = test.stdout[:100] if test.stdout else test.stderr
        except Exception as e:
            info['version_test'] = False
            info['version_error'] = str(e)
    
    return jsonify(info)

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🎬 AniMotion Web Interface Starting...")
    print("="*60)
    print(f"📁 Base Directory: {BASE_DIR}")
    print(f"📁 Upload Folder: {UPLOAD_FOLDER}")
    print(f"📁 Output Folder: {OUTPUT_FOLDER}")
    print(f"📁 Input Folder: {INPUT_FOLDER}")
    print(f"📁 Assets Folder: {ASSETS_FOLDER}")
    
    # Check components
    extract_exists = os.path.exists(os.path.join(BASE_DIR, 'extract_pose.py'))
    blender_exists = os.path.exists(os.path.join(BLENDER_FOLDER, 'auto_oneclick.py'))
    blender_exe = find_blender_executable()
    
    print("\n📋 Component Check:")
    print(f"   extract_pose.py: {'✅' if extract_exists else '❌'}")
    print(f"   auto_oneclick.py: {'✅' if blender_exists else '❌'}")
    print(f"   Blender: {'✅ ' + blender_exe if blender_exe else '❌ Not Found'}")
    
    if not extract_exists:
        print("\n⚠️  WARNING: extract_pose.py not found!")
    if not blender_exists:
        print("\n⚠️  WARNING: Blender/auto_oneclick.py not found!")
    if not blender_exe:
        print("\n⚠️  WARNING: Blender not found! Install Blender 4.x or set BLENDER_PATH")
    
    print("\n🚀 Starting Flask server on http://127.0.0.1:5000")
    print("="*60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)