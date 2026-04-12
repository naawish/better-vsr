# core/paths.py
import os
import sys

def get_resource_path(relative_path):
    """
    Finds resources (FFmpeg, Model) inside the temporary 
    unpack directory for Nuitka One-File builds.
    """
    # 1. Get the directory where paths.py is located
    # In dev: BetterVSR/core/
    # In EXE: C:/Users/.../Temp/ONEFIL~1/core/
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 2. Go up one level to reach the root folder
    root_dir = os.path.dirname(current_dir)
    
    # 3. Combine and normalize the path (fixes the / vs \ issue on Windows)
    target_path = os.path.join(root_dir, relative_path)
    
    return os.path.normpath(target_path)