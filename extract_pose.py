import cv2
import mediapipe as mp
import json
import os
import sys

def main():
    # Get video path from command line argument or use default
    if len(sys.argv) > 1:
        video_path = sys.argv[1]
    else:
        video_path = "input/vid6.mp4"
    
    output_path = "output/pose_data.json"
    
    print("Starting pose extraction from: " + video_path)
    
    # Check if video exists
    if not os.path.exists(video_path):
        print("ERROR: Video file not found: " + video_path)
        return False
    
    # Initialize MediaPipe Pose
    mp_pose = mp.solutions.pose
    pose = mp_pose.Pose()
    
    # Open video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("ERROR: Cannot open video")
        return False
    
    pose_data = []
    frame_count = 0
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
                
            # Convert and process
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(rgb_frame)
            
            if results.pose_landmarks:
                frame_landmarks = []
                for landmark in results.pose_landmarks.landmark:
                    frame_landmarks.append({
                        'x': float(landmark.x),
                        'y': float(landmark.y), 
                        'z': float(landmark.z),
                        'visibility': float(landmark.visibility)
                    })
                pose_data.append(frame_landmarks)
            else:
                pose_data.append([])
            
            frame_count += 1
            if frame_count % 30 == 0:
                print("Frames processed: " + str(frame_count))
                
    except Exception as e:
        print("Error during processing: " + str(e))
        return False
    finally:
        cap.release()
    
    # Save data
    os.makedirs("output", exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(pose_data, f)
    
    print("SUCCESS: Saved " + str(frame_count) + " frames to " + output_path)
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)