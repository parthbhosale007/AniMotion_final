import cv2
import mediapipe as mp
import json
import os

def extract_pose_from_video(video_path, output_json_path):
    print("Starting pose extraction...")
    
    # Initialize MediaPipe Pose
    mp_pose = mp.solutions.pose
    pose = mp_pose.Pose(
        static_image_mode=False,
        model_complexity=1,
        smooth_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )
    
    # Open video file
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("ERROR: Could not open video file")
        return False
    
    pose_data = []
    frame_count = 0
    
    print("Processing video frames...")
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
            
        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Process frame with MediaPipe
        results = pose.process(rgb_frame)
        
        if results.pose_landmarks:
            landmarks = []
            for landmark in results.pose_landmarks.landmark:
                landmarks.append({
                    'x': landmark.x,
                    'y': landmark.y, 
                    'z': landmark.z,
                    'visibility': landmark.visibility
                })
            pose_data.append(landmarks)
        else:
            pose_data.append([])  # No pose detected
        
        frame_count += 1
        if frame_count % 30 == 0:
            print(f"Processed {frame_count} frames...")
    
    # Release resources
    cap.release()
    pose.close()
    
    # Save pose data to JSON
    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
    with open(output_json_path, 'w') as f:
        json.dump(pose_data, f, indent=2)
    
    print(f"SUCCESS: Pose data saved to {output_json_path}")
    print(f"Total frames processed: {frame_count}")
    
    return True

if __name__ == "__main__":
    # These will be replaced by Flask
    video_path = r"c:\Users\admin\Desktop\AniMotion\input\vid6.mp4"
    output_path = "output/pose_data.json"
    
    success = extract_pose_from_video(video_path, output_path)
    if not success:
        exit(1)