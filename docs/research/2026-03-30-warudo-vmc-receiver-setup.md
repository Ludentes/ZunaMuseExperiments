# Warudo VMC Receiver Setup Guide

**Date**: 2026-03-30
**Source**: https://docs.warudo.app/docs/mocap/vmc + related handbook pages

## Key Finding: There Is No Standalone "VMC Receiver" Menu

Warudo does **not** have a separate "Motion Capture" settings panel or a standalone "VMC Receiver" asset in the Assets menu. The VMC receiver is created **automatically** when you set up motion capture on a Character. You will not find it by browsing menus manually.

## Prerequisites

1. You **must load a character model first** (`.vrm` or `.warudo` format)
2. Place your model file in Warudo's `Characters` folder (click "Open Characters Folder" in the UI)

## Step-by-Step Setup

### Method 1: Onboarding Assistant (Recommended for First Time)

1. In the scene, click **Basic Setup -> Get Started**
2. Select your character model from the dropdown
3. When asked about motion capture recommendations, choose **"No"** (manual selection)
4. For **Face Tracking**, select **VMC** (or skip if not needed)
5. For **Pose Tracking**, select **VMC**
6. Confirm your selections
7. Warudo auto-generates a **VMC Receiver** asset and tracking **blueprints** that connect VMC data to your character

### Method 2: Character Asset Setup (If Already Have a Character Loaded)

1. Select your **Character** asset in the Assets panel (left sidebar)
2. Click **Setup Motion Capture** button on the character asset
3. Choose **VMC** as the face/pose tracking source
4. Warudo creates the VMC receiver and blueprints automatically

## VMC Receiver Configuration

- **Default port**: `39539` (matches VMC protocol standard)
- The receiver is created as an internal asset -- you should see it appear after setup
- **Do NOT manually create a VMC receiver** via "Add Asset" -- it won't be wired to your character

## Sending VMC Data to Warudo

From your external application, send to:
- **Host**: `127.0.0.1` (localhost) or Warudo machine's IP
- **Port**: `39539` (default)

### Example: VSeeFace as Sender
- General Settings -> VMC Protocol -> check "Send data with VMC protocol"
- Default port 39539

### Example: VirtualMotionCapture as Sender
- Settings -> VMCProtocol Motion sender -> enable "OSC motion sender"
- Default port 39539

## Troubleshooting

### Character in extremely weird poses
- **Must load the same model** in both Warudo and the external app (for VRM-based senders)
- Model must have **normalized bones** (zero rotation in T-pose)
- For VRM: re-export with "Enforce T-Pose" checked if needed

### Tracking is jittery or too smooth
- In the generated blueprint, find **Smooth Rotation List** / **Smooth Position List** / **Smooth Transform** / **Smooth BlendShape List** nodes
- Increase **Smooth Time** for smoother tracking, decrease for more responsive

### Can't find motion capture settings
- There is no top-level "Motion Capture" menu -- it's always accessed through the **Character asset** or the **onboarding assistant**
- The VMC Receiver asset is auto-generated, not manually created

## Important Notes

- **VMC Sender** (outbound) exists as a standalone asset in Assets menu -- this is for *sending* data FROM Warudo, not receiving
- **VMC Receiver** (inbound) is only created via Setup Motion Capture or onboarding -- never manually
- The onboarding assistant **removes existing motion capture configs** when re-run, so use "Character -> Setup Motion Capture" if adding a second tracking source
- Warudo generates **blueprints** (visual scripts) that wire the VMC data to character bones/blendshapes -- these can be customized after setup

## For Our Muse-VTuber Bridge

Our bridge sends VMC protocol data. To connect:
1. Load any VRM model in Warudo
2. Use Character -> Setup Motion Capture -> select VMC
3. Our bridge should send to `127.0.0.1:39539`
4. The same VRM model does NOT need to match (we're sending bone rotations, not model-specific data)
