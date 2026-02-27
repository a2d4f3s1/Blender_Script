"""
ボーン位置固定スクリプト（足滑り / スライディング修正）
v1.0
対象: Blender 4.2
実行: テキストエディタで開き Alt+P (または [Run Script])

【使い方】
  1. アーマチュアを Pose Mode にして対象ボーンをアクティブ選択
  2. CONFIGURATION を編集
  3. スクリプト実行（開始フレーム = 実行時のカレントフレーム）

【処理の概要】
  Empty の動きをボーンのワールド座標から「打ち消す」ことで、
  Empty が frame_start で静止していた場合と同じ軌跡をボーンにトレースさせる。
  ボーン自身のアニメーション（足の上げ下ろし等）は完全に保持される。

  desired_bone_world = empty_w_start @ empty_w_t.inverted() @ bone_w_t
"""

import bpy

# ================================================================
# CONFIGURATION  ← ここを編集してください
# ================================================================

EMPTY_NAME = "Empty"    # Root Empty オブジェクトの名前
                        # ※ アーマチュアはアクティブオブジェクトから自動取得

FRAME_END = 100         # 補正終了フレーム
                        # ※ 開始フレーム = スクリプト実行時のカレントフレーム（基準位置も兼ねる）

FIX_X = True            # ワールド X 軸の補正を適用する（水平・左右）
FIX_Y = True            # ワールド Y 軸の補正を適用する（水平・奥行き）
FIX_Z = True           # ワールド Z 軸の補正を適用する（通常 False = 縦・上下は Empty に追従）

# ================================================================


def main():
    scene = bpy.context.scene

    # ---- Empty 検証 ----
    empty = bpy.data.objects.get(EMPTY_NAME)
    if empty is None:
        print(f"[ERROR] Empty '{EMPTY_NAME}' が見つかりません")
        return

    # ---- アクティブオブジェクト（アーマチュア）検証 ----
    armature = bpy.context.active_object
    if armature is None or armature.type != 'ARMATURE':
        print("[ERROR] アクティブオブジェクトがアーマチュアではありません。Pose Mode でアーマチュアを選択してください")
        return

    # ---- アクティブボーン検証 ----
    pose_bone = bpy.context.active_pose_bone
    if pose_bone is None:
        print("[ERROR] アクティブなポーズボーンがありません。Pose Mode でボーンを選択してください")
        return

    # ---- フレーム範囲 ----
    frame_start = scene.frame_current
    frame_end   = FRAME_END

    if frame_start > frame_end:
        print(f"[ERROR] カレントフレーム ({frame_start}) が FRAME_END ({frame_end}) より後です")
        return

    # ---- 回転モード確認（ボーンの設定に従う）----
    rot_mode = pose_bone.rotation_mode  # 'QUATERNION' / 'AXIS_ANGLE' / 'XYZ' 等

    print("=" * 52)
    print(f"  対象ボーン  : {pose_bone.name}")
    print(f"  アーマチュア: {armature.name}")
    print(f"  回転モード  : {rot_mode}")
    print(f"  フレーム範囲: {frame_start} → {frame_end}")
    axes = " ".join(a for a, f in [("X", FIX_X), ("Y", FIX_Y), ("Z", FIX_Z)] if f) or "なし"
    print(f"  補正軸      : {axes}")
    print("=" * 52)

    saved_frame = frame_start

    # ================================================================
    # Phase 1: 全フレームのワールド行列を事前サンプリング
    #          ※ この時点では何も変更しない（累積誤差を防ぐため）
    # ================================================================
    print("[INFO] Phase 1: サンプリング中...")

    samples = {}
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()

        # armature.matrix_world は評価済み行列。
        # Empty の回転・移動、Child Of 等のコンストレイントも含む。
        arm_w = armature.matrix_world.copy()

        # ボーンのワールド行列 = アーマチュアW行列 × ボーンのアーマチュア空間行列
        bone_w = (arm_w @ pose_bone.matrix).copy()

        # Empty のワールド行列（評価済み）
        empty_w = empty.matrix_world.copy()

        samples[frame] = {
            "arm_w":   arm_w,
            "bone_w":  bone_w,
            "empty_w": empty_w,
        }

    # 開始フレームの Empty ワールド行列 = 「静止基準」
    empty_w_start = samples[frame_start]["empty_w"]

    t = empty_w_start.translation
    print(f"[INFO] 基準フレーム {frame_start} の Empty 位置: ({t.x:.3f}, {t.y:.3f}, {t.z:.3f})")

    # ================================================================
    # Phase 2: 補正を適用し location / rotation キーフレームを挿入
    #
    #   desired_bone_world = empty_w_start @ empty_w_t.inverted() @ bone_w_t
    #
    #   ・empty_w_t.inverted() で現フレームの Empty 変位を除去
    #   ・empty_w_start で基準フレームの Empty 姿勢を乗せ直す
    #   ・bone_w_t のボーン自身のアニメーションは完全保存
    # ================================================================
    print("[INFO] Phase 2: 補正キーフレーム適用中...")

    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()

        s       = samples[frame]
        bone_w  = s["bone_w"]
        arm_w   = s["arm_w"]
        empty_w = s["empty_w"]

        # ---- Empty の動きを除去し、基準姿勢を乗せ直した目標ワールド行列 ----
        desired_bone_w = empty_w_start @ empty_w.inverted() @ bone_w

        # ---- FIX_X/Y/Z: 補正量の平行移動成分に軸マスクを適用 ----
        #   補正しない軸は元のボーン世界座標を維持する
        delta = desired_bone_w.translation - bone_w.translation
        if not FIX_X: delta.x = 0.0
        if not FIX_Y: delta.y = 0.0
        if not FIX_Z: delta.z = 0.0
        desired_bone_w.translation = bone_w.translation + delta

        # ---- アーマチュアローカル空間に変換してボーンに適用 ----
        pose_bone.matrix = arm_w.inverted() @ desired_bone_w
        bpy.context.view_layer.update()

        # ---- location キーフレーム挿入 ----
        pose_bone.keyframe_insert(data_path="location", frame=frame)

        # ---- rotation キーフレーム挿入（ボーンの rotation_mode に従う）----
        if rot_mode == 'QUATERNION':
            pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        elif rot_mode == 'AXIS_ANGLE':
            pose_bone.keyframe_insert(data_path="rotation_axis_angle", frame=frame)
        else:
            # XYZ / XZY / YXZ / YZX / ZXY / ZYX
            pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame)

    # ---- 元フレームに戻す ----
    scene.frame_set(saved_frame)
    bpy.context.view_layer.update()

    total = frame_end - frame_start + 1
    msg = f"完了！ {total} フレーム ({frame_start}→{frame_end}) に location / rotation キーを設定しました"
    print(f"[INFO] {msg}")

    # ---- 完了ポップアップ（画面下部に表示）----
    def draw_popup(self, context):
        self.layout.label(text=msg)

    bpy.context.window_manager.popup_menu(draw_popup, title="Bone Sliding Fix", icon='CHECKMARK')


main()
