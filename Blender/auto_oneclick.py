# Blender/auto_oneclick.py
# One-click, headless: JSON -> Mixamo rig baked -> FBX + MP4
# Requires Blender 4.x (bundled NumPy OK). No SciPy needed.

import bpy, json, os, math
import numpy as np
import mathutils

# ------------------- CONFIG -------------------
JSON_PATH   = bpy.path.abspath("//output/pose_data.json")
CHAR_FBX    = bpy.path.abspath("//assets/character.fbx")   # Mixamo character (T-pose)
OUT_FBX     = bpy.path.abspath("//output/skinned_animation.fbx")
OUT_MP4     = bpy.path.abspath("//output/anim.mp4")

VIDEO_W, VIDEO_H = 640, 480
SCALE          = 2.0
START_FRAME    = 1
SMOOTH_WINDOW  = 9   # odd, >=3
FPS            = 30
RENDER_PREVIEW = False   # set False to skip MP4
# ------------------------------------------------

def safe_clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for b in bpy.data.actions: bpy.data.actions.remove(b)

def load_pose_json(path):
    with open(path, "r") as f:
        data = json.load(f)
    if not data:
        raise ValueError("Pose JSON empty.")
    return data

def moving_average(arr, win):
    if win < 3 or win % 2 == 0: return arr
    k = np.ones(win) / win
    # pad at ends to keep same length
    pad = win // 2
    arr_p = np.pad(arr, ((pad,pad),(0,0),(0,0)), mode='edge')
    out = np.empty_like(arr)
    for i in range(arr.shape[2]):  # x,y,z
        out[:,:,i] = np.apply_along_axis(lambda m: np.convolve(m, k, mode='valid'), 0, arr_p[:,:,i])
    return out

def norm_to_world(lm, sx, sy, sz):
    x = (lm[0] - 0.5) * VIDEO_W / 100.0 * SCALE * sx
    y = (lm[1] - 0.5) * VIDEO_H / 100.0 * SCALE * sy
    z = -lm[2] * SCALE * sz
    return (x, y, z)

def mid(a, b):
    return ( (a[0]+b[0])/2.0, (a[1]+b[1])/2.0, (a[2]+b[2])/2.0 )

def ensure_camera_light():
    cam = None
    for obj in bpy.data.objects:
        if obj.type == 'CAMERA':
            cam = obj
            break
    if cam is None:
        cam_data = bpy.data.cameras.new("AutoCamera")
        cam = bpy.data.objects.new("AutoCamera", cam_data)
        bpy.context.collection.objects.link(cam)
    
    # Position camera further away
    cam.location = (12, -12, 8)
    cam.rotation_euler = (1.1, 0, 0.78)  # facing toward origin
    bpy.context.scene.camera = cam
    print(" Camera positioned:", cam.location)

    # --- Light ---
    light = None
    for obj in bpy.data.objects:
        if obj.type == 'LIGHT':
            light = obj
            break
    if light is None:
        light_data = bpy.data.lights.new("AutoLight", type='SUN')
        light = bpy.data.objects.new("AutoLight", light_data)
        bpy.context.collection.objects.link(light)
        light.location = (10, -10, 15)
        print(" Light created: AutoLight")


def import_mixamo(path):
    pre_objs = set(bpy.data.objects)
    try:
        bpy.ops.import_scene.fbx(filepath=path)
    except RuntimeError as e:
        if "Version 6100 unsupported" in str(e):
            print(" FBX version too old! Please re-download from Mixamo or convert to newer FBX format.")
            print("   Mixamo should export FBX 7.4 binary by default now.")
        raise e
    
    post_objs = set(bpy.data.objects)
    new = list(post_objs - pre_objs)
    arm = next((o for o in new if o.type=='ARMATURE'), None)
    if not arm:
        # try any armature in scene
        arm = next((o for o in bpy.data.objects if o.type=='ARMATURE'), None)
    if not arm:
        raise RuntimeError("No armature found after FBX import.")
    arm.name = "CharacterArmature"
    return arm

def get_bone(o, name):
    return o.pose.bones.get(name)

def resolve_bone(rig, name):
    """Try to get bone with mixamorig: prefix, fallback to without prefix"""
    pb = get_bone(rig, name)
    if pb: return pb
    return get_bone(rig, name.split(":")[-1])

def vector_to_quat(vec, rest_axis):
    """
    Converts a world-space vector into a quaternion aligning rest_axis -> vec.
    """
    vec = vec.normalized()
    rest_axis = rest_axis.normalized()
    rot_axis = rest_axis.cross(vec)
    if rot_axis.length < 1e-6:  # parallel
        return mathutils.Quaternion()
    rot_axis.normalize()
    angle = rest_axis.angle(vec)
    return mathutils.Quaternion(rot_axis, angle)



def vector_to_quaternion(target_vector, bone_local_axis=(0, 1, 0)):
    """
    Compute quaternion to align bone_local_axis with target_vector
    Most Mixamo bones point down their local Y-axis by default
    """
    if target_vector.length < 1e-6:
        return mathutils.Quaternion()  # identity
    
    local_axis = mathutils.Vector(bone_local_axis).normalized()
    target_normalized = target_vector.normalized()
    
    # Quaternion to rotate local_axis to target_normalized
    return local_axis.rotation_difference(target_normalized)

# Global orientation correction (rotates rig from lying upside down to upright)
GLOBAL_CORRECTION = mathutils.Euler((-1.5708, 0, 0), 'XYZ').to_quaternion()
# Mixamo correction dictionary
BONE_CORRECTIONS = {
    "mixamorig:LeftArm": mathutils.Euler((0, 0, -90), 'XYZ').to_quaternion(),
    "mixamorig:RightArm": mathutils.Euler((0, 0, 90), 'XYZ').to_quaternion(),
    "mixamorig:Hips": mathutils.Quaternion((1,0,0,0)),  # identity
    "mixamorig:Spine": mathutils.Quaternion((1,0,0,0)),
    "mixamorig:LeftUpLeg": mathutils.Quaternion((1,0,0,0)),
    "mixamorig:RightUpLeg": mathutils.Quaternion((1,0,0,0)),
    "mixamorig:Head": mathutils.Quaternion((1,0,0,0)),
}

def apply_quaternion_animation(rig, landmark_data_world, frame_count):
    """
    Apply quaternion-based animation to Mixamo rig bones with improved handling
    """
    print(f"🎬 Applying animation to {frame_count} frames...")
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='POSE')
    
    # Clear any existing animation first
    rig.animation_data_clear()
    
    # MediaPipe pose landmark indices
    mp_indices = {
        'nose': 0, 'left_shoulder': 11, 'right_shoulder': 12,
        'left_elbow': 13, 'left_wrist': 15, 'right_elbow': 14, 'right_wrist': 16,
        'left_hip': 23, 'right_hip': 24, 'left_knee': 25, 'left_ankle': 27,
        'right_knee': 26, 'right_ankle': 28
    }
    
    # Simplified bone mappings for debugging - start with just a few key bones
    bone_mappings = [
        ("mixamorig:Hips", 'hip_center', 'shoulder_center'),
        ("mixamorig:Spine", 'hip_center', 'shoulder_center'),
        ("mixamorig:LeftArm", 'left_shoulder', 'left_elbow'),
        ("mixamorig:RightArm", 'right_shoulder', 'right_elbow'),
        ("mixamorig:LeftUpLeg", 'left_hip', 'left_knee'),
        ("mixamorig:RightUpLeg", 'right_hip', 'right_knee'),
    ]
    
    print(f" DEBUG: Testing {len(bone_mappings)} key bones...")
    
    # Check which bones exist
    existing_bones = []
    for bone_name, from_key, to_key in bone_mappings:
        bone = resolve_bone(rig, bone_name)
        if bone:
            existing_bones.append((bone_name, from_key, to_key, bone))
            print(f" Found: {bone.name}")
        else:
            print(f" Missing: {bone_name}")
    
    if not existing_bones:
        print(" ERROR: No bones found! Check bone names.")
        # Let's see what bones ARE available
        print(" Available bones in rig:")
        for i, bone in enumerate(rig.pose.bones):
            if i < 20:  # Show first 20
                print(f"   {bone.name}")
            elif i == 20:
                print(f"   ... and {len(rig.pose.bones)-20} more")
                break
        return
    
    print(f" Will animate {len(existing_bones)} bones")
    
    # Simple direct animation - full range
    for frame_idx in range(frame_count):
        frame_num = START_FRAME + frame_idx
        bpy.context.scene.frame_set(frame_num)
    
        # Get landmark positions for this frame
        landmarks = landmark_data_world[frame_idx]
    
        # Derived positions
        hip_center = mid(landmarks[mp_indices['left_hip']], landmarks[mp_indices['right_hip']])
        shoulder_center = mid(landmarks[mp_indices['left_shoulder']], landmarks[mp_indices['right_shoulder']])
    
        positions = {
            'hip_center': mathutils.Vector(hip_center),
            'shoulder_center': mathutils.Vector(shoulder_center),
            'nose': mathutils.Vector(landmarks[mp_indices['nose']]),
            'left_shoulder': mathutils.Vector(landmarks[mp_indices['left_shoulder']]),
            'right_shoulder': mathutils.Vector(landmarks[mp_indices['right_shoulder']]),
            'left_elbow': mathutils.Vector(landmarks[mp_indices['left_elbow']]),
            'left_wrist': mathutils.Vector(landmarks[mp_indices['left_wrist']]),
            'right_elbow': mathutils.Vector(landmarks[mp_indices['right_elbow']]),
            'right_wrist': mathutils.Vector(landmarks[mp_indices['right_wrist']]),
            'left_hip': mathutils.Vector(landmarks[mp_indices['left_hip']]),
            'right_hip': mathutils.Vector(landmarks[mp_indices['right_hip']]),
            'left_knee': mathutils.Vector(landmarks[mp_indices['left_knee']]),
            'left_ankle': mathutils.Vector(landmarks[mp_indices['left_ankle']]),
            'right_knee': mathutils.Vector(landmarks[mp_indices['right_knee']]),
            'right_ankle': mathutils.Vector(landmarks[mp_indices['right_ankle']]),
        }
    
        for bone_name, from_key, to_key, bone in existing_bones:
            from_pos = positions.get(from_key)
            to_pos   = positions.get(to_key)
            if from_pos is None or to_pos is None:
                continue
            target_vector = to_pos - from_pos
            if target_vector.length < 1e-6:
                continue
    
            # Hips: set location (converted to armature local)
            if bone_name == "mixamorig:Hips":
                hip_local = rig.matrix_world.inverted() @ mathutils.Vector(hip_center)
                bone.location = hip_local
                bone.keyframe_insert("location", frame=frame_num)
    
            # Put a simple rotation for now (replace with real quaternion math later)
            # Using a small rotation proportional to frame index to ensure keyframes exist:
            # test_rotation = mathutils.Quaternion((1, 0, 0), math.radians(5 * (frame_idx % 72)))
            # Step: Convert landmark vector into quaternion
            rest_axis = mathutils.Vector((0, 1, 0))  # Mixamo bones usually rest along +Y
            quat = vector_to_quat(target_vector, rest_axis)
            
            # Step: Apply correction
            corr = BONE_CORRECTIONS.get(bone_name, mathutils.Quaternion((1,0,0,0)))
            final_quat = corr @ quat
            
            # Step: Insert keyframe
            bone.rotation_mode = 'QUATERNION'
            bone.rotation_quaternion = final_quat
            bone.keyframe_insert("rotation_quaternion", frame=frame_num)


    # After we finish, set the scene range to match the full animation
    bpy.context.scene.frame_start = START_FRAME
    bpy.context.scene.frame_end   = START_FRAME + frame_count - 1
    print(f" Scene frame range set: {bpy.context.scene.frame_start}..{bpy.context.scene.frame_end}")

def bake_pose(obj, f_start, f_end):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.nla.bake(
        frame_start=f_start,
        frame_end=f_end,
        only_selected=False,
        visual_keying=True,
        clear_constraints=True,
        use_current_action=True,
        bake_types={'POSE'}
    )

def setup_render(fps, out_mp4, frame_end):
    s = bpy.context.scene
    s.render.engine = 'BLENDER_EEVEE_NEXT' 
    s.render.fps = fps
    s.frame_start = START_FRAME
    s.frame_end = START_FRAME + frame_end - 1
    s.render.image_settings.file_format = 'FFMPEG'
    s.render.ffmpeg.format = 'MPEG4'
    s.render.ffmpeg.codec = 'H264'
    s.render.ffmpeg.constant_rate_factor = 'MEDIUM'
    s.render.ffmpeg.ffmpeg_preset = 'GOOD'
    s.render.filepath = out_mp4

def check_inputs_or_die():
    json_abs = bpy.path.abspath(JSON_PATH)
    fbx_abs  = bpy.path.abspath(CHAR_FBX)
    out_fbx_abs = bpy.path.abspath(OUT_FBX)
    out_mp4_abs = bpy.path.abspath(OUT_MP4)

    print("\n--- PATH CHECK ---")
    print("JSON_PATH:", json_abs, "exists:", os.path.exists(json_abs))
    print("CHAR_FBX :", fbx_abs,  "exists:", os.path.exists(fbx_abs))
    print("OUT_FBX  :", out_fbx_abs)
    print("OUT_MP4  :", out_mp4_abs)
    print("Blend file:", bpy.data.filepath if bpy.data.filepath else "(unsaved!)")
    print("------------------\n")

    if not os.path.exists(json_abs):
        raise FileNotFoundError(
            f"Pose JSON not found at {json_abs}.\n"
            "Tip: Save your .blend so // resolves correctly, or use absolute paths."
        )
    if not os.path.exists(fbx_abs):
        raise FileNotFoundError(
            f"Character FBX not found at {fbx_abs}.\n"
            "Tip: Save your .blend so // resolves correctly, or use absolute paths."
        )


# ------------------- PIPELINE -------------------

check_inputs_or_die()

safe_clear_scene()
ensure_camera_light()

# 1) Load and smooth
pose = load_pose_json(JSON_PATH)
T = len(pose)
L = len(pose[0]["landmarks"])
arr = np.array([[[lm["x"], lm["y"], lm["z"]] for lm in f["landmarks"]] for f in pose], dtype=np.float32)
arr_s = moving_average(arr, SMOOTH_WINDOW)

print(f" Loaded pose JSON frames: {T}, landmarks per frame: {L}")
# show indices of first and last frames (first landmark of each)
print("First landmark sample:", pose[0]["landmarks"][0])
print("Last landmark sample:", pose[-1]["landmarks"][0])


# 2) Convert landmarks to world coordinates
landmark_data_world = {}
for frame_idx in range(T):
    frame_landmarks = []
    for lm_idx in range(L):
        world_pos = norm_to_world(arr_s[frame_idx, lm_idx], sx=1, sy=1, sz=1)
        frame_landmarks.append(world_pos)
    landmark_data_world[frame_idx] = frame_landmarks

# 3) Import character
rig = import_mixamo(CHAR_FBX)
print(f" Mixamo rig: {rig.name}")

# --- Ensure imported meshes are visible and bound to the armature ---
imported_meshes = []
# new objects from import may or may not be in 'new' var earlier; find meshes with no parent or with armature modifier
for obj in bpy.data.objects:
    if obj.type == 'MESH' and obj.name not in ("Cube",):
        # consider it an imported mesh candidate if it shares armature modifier or is nearby
        imported_meshes.append(obj)

if not imported_meshes:
    print("  No meshes found after FBX import. Check FBX content.")
else:
    print(f" Found {len(imported_meshes)} mesh(es). Making sure they use the armature...")
for m in imported_meshes:
    # unhide
    m.hide_viewport = False
    m.hide_render = False
    m.select_set(False)
    # ensure an armature modifier exists
    arm_mod = None
    for mod in m.modifiers:
        if mod.type == 'ARMATURE':
            arm_mod = mod
            break
    if arm_mod is None:
        arm_mod = m.modifiers.new("Armature", 'ARMATURE')
    arm_mod.object = rig
    # parent to rig (keeps transform)
    m.parent = rig
    m.matrix_parent_inverse = rig.matrix_world.inverted() @ m.matrix_world
    print(f"   ✓ Mesh '{m.name}' assigned Armature modifier -> {rig.name}")


# 4) Auto-scale/align rig to MediaPipe data using hip/shoulder centers
# MediaPipe indices: LShoulder=11, RShoulder=12, LHip=23, RHip=24
mp_LS, mp_RS, mp_LH, mp_RH = 11, 12, 23, 24

# Get first-frame positions to estimate scale
first_frame = landmark_data_world[0]
p_ls = mathutils.Vector(first_frame[mp_LS])
p_rs = mathutils.Vector(first_frame[mp_RS])
p_lh = mathutils.Vector(first_frame[mp_LH])
p_rh = mathutils.Vector(first_frame[mp_RH])

mp_shoulder_center = (p_ls + p_rs) / 2
mp_hip_center = (p_lh + p_rh) / 2
mp_torso_len = (mp_shoulder_center - mp_hip_center).length

# Character rig distances
hips = get_bone(rig, "mixamorig:Hips") or get_bone(rig, "Hips")
neck = get_bone(rig, "mixamorig:Neck") or get_bone(rig, "Neck") \
       or get_bone(rig, "mixamorig:Spine2") or get_bone(rig, "Spine2")

if hips and neck:
    rig_hips_w = rig.matrix_world @ hips.head
    rig_neck_w = rig.matrix_world @ neck.head
    rig_torso_len = (rig_neck_w - rig_hips_w).length
    
    if mp_torso_len > 1e-6 and rig_torso_len > 1e-6:
        scale = rig_torso_len / mp_torso_len
        rig.scale = (scale, scale, scale)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    # Position rig at MediaPipe hip center
    rig.location = mp_hip_center
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

# 5) Apply quaternion-based animation (NEW APPROACH)
apply_quaternion_animation(rig, landmark_data_world, T)

# 6) Bake to the character rig
frame_end = T
bake_pose(rig, START_FRAME, START_FRAME + frame_end - 1)

# 7) Export FBX (select rig + meshes)
bpy.ops.object.mode_set(mode='OBJECT', toggle=False)  # ensure OBJECT mode

# Deselect everything safely (without bpy.ops)
for obj in bpy.context.selected_objects:
    obj.select_set(False)

# Select rig + imported meshes
rig.select_set(True)
for m in imported_meshes:
    m.select_set(True)

# Set rig as active
bpy.context.view_layer.objects.active = rig

print(f"\nFBX export starting… '{OUT_FBX}'")
bpy.ops.export_scene.fbx(
    filepath=OUT_FBX,
    use_selection=True,
    bake_anim=True,
    add_leaf_bones=False,
    bake_anim_use_nla_strips=False,
    bake_anim_use_all_actions=False
)
print(f" FBX written: {OUT_FBX}")

# 8) (Optional) MP4 preview render
if RENDER_PREVIEW:
    ensure_camera_light()
    setup_render(FPS, OUT_MP4, frame_end)
    print(f"\n Rendering MP4 preview to '{OUT_MP4}' …")
    bpy.ops.render.render(animation=True)
    print(f" MP4 written: {OUT_MP4}")