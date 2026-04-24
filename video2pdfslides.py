import argparse
import glob
import os
import shutil
import time

import cv2
import img2pdf

OUTPUT_SLIDES_DIR = "./output"

DEFAULT_SAMPLE_RATE = 6.0
DEFAULT_WARMUP_SECONDS = 1.0
DEFAULT_HISTORY_SECONDS = 6.0
DEFAULT_VAR_THRESHOLD = 16
DEFAULT_DETECT_SHADOWS = False
DEFAULT_MIN_STILL_PERCENT = 0.35
DEFAULT_RESET_MOTION_PERCENT = 0.9
DEFAULT_MIN_STILL_FRAMES = 2
DEFAULT_RESET_FRAMES = 2
DEFAULT_RESIZE_WIDTH = 600
DEFAULT_DEDUPE_PERCENT = 0.5
DEFAULT_DEDUPE_PIXEL_THRESHOLD = 18
DEFAULT_COLLAPSE_MONOTONIC_BUILD = False
DEFAULT_MONOTONIC_MIN_ADD_PERCENT = 0.15
DEFAULT_MONOTONIC_MAX_REMOVE_PERCENT = 0.03
DEFAULT_MONOTONIC_MIN_CONTAINMENT = 0.97


def frame_change_percent(gray_a, gray_b, pixel_threshold):
    diff = cv2.absdiff(gray_a, gray_b)
    _, binary = cv2.threshold(diff, pixel_threshold, 255, cv2.THRESH_BINARY)
    return (cv2.countNonZero(binary) / float(binary.shape[0] * binary.shape[1])) * 100


def extract_content_mask(gray):
    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    _, global_mask = cv2.threshold(enhanced, 245, 255, cv2.THRESH_BINARY_INV)
    adaptive_mask = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        10,
    )
    mask = cv2.bitwise_or(global_mask, adaptive_mask)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    return mask


def monotonic_growth_stats(old_mask, new_mask):
    old_count = cv2.countNonZero(old_mask)
    new_count = cv2.countNonZero(new_mask)
    if old_count == 0 or new_count == 0:
        return 0.0, 0.0, 0.0

    intersection = cv2.bitwise_and(old_mask, new_mask)
    added = cv2.bitwise_and(new_mask, cv2.bitwise_not(old_mask))
    removed = cv2.bitwise_and(old_mask, cv2.bitwise_not(new_mask))

    total_pixels = float(old_mask.shape[0] * old_mask.shape[1])
    containment = cv2.countNonZero(intersection) / float(old_count)
    add_percent = (cv2.countNonZero(added) / total_pixels) * 100
    remove_percent = (cv2.countNonZero(removed) / total_pixels) * 100
    return containment, add_percent, remove_percent


def preprocess_frame(frame, resize_width):
    processed = cv2.resize(
        frame,
        (resize_width, int(frame.shape[0] * (resize_width / float(frame.shape[1])))),
        interpolation=cv2.INTER_AREA,
    )
    gray = cv2.cvtColor(processed, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    return processed, gray


def get_frames(video_path, sample_rate, warmup_seconds):
    vs = cv2.VideoCapture(video_path)
    if not vs.isOpened():
        raise RuntimeError(f"unable to open file {video_path}")

    source_fps = vs.get(cv2.CAP_PROP_FPS)
    if source_fps <= 0:
        source_fps = sample_rate

    frame_step = max(1, int(round(source_fps / sample_rate)))
    warmup_frames = max(0, int(round(warmup_seconds * source_fps)))
    total_frames = int(vs.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    print("total_frames:", total_frames)
    print("source_fps:", source_fps)
    print("sample_rate:", sample_rate)
    print("frame_step:", frame_step)

    frame_index = -1
    yielded_count = 0

    while True:
        ok, frame = vs.read()
        if not ok or frame is None:
            break

        frame_index += 1
        if frame_index < warmup_frames:
            continue
        if frame_index % frame_step != 0:
            continue

        frame_time = frame_index / float(source_fps)
        yielded_count += 1
        yield yielded_count, frame_index, frame_time, frame

    vs.release()


def detect_unique_screenshots(video_path, output_folder_screenshot_path, args):
    history = max(1, int(round(args.sample_rate * args.history_seconds)))
    fgbg = cv2.createBackgroundSubtractorMOG2(
        history=history,
        varThreshold=args.var_threshold,
        detectShadows=args.detect_shadows,
    )

    start_time = time.time()
    saved_count = 0
    stable_count = 0
    motion_count = 0
    stable_segment_saved = False
    last_saved_gray = None
    last_saved_mask = None
    last_saved_path = None
    candidate_orig = None
    candidate_gray = None
    candidate_time = 0.0
    candidate_frame_index = -1
    last_diff_percent = None

    for sample_index, frame_index, frame_time, frame in get_frames(
        video_path, args.sample_rate, args.warmup_seconds
    ):
        orig = frame.copy()
        resized, gray = preprocess_frame(frame, args.resize_width)
        mask = fgbg.apply(gray)

        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        height, width = mask.shape[:2]
        diff_percent = (cv2.countNonZero(mask) / float(width * height)) * 100
        last_diff_percent = diff_percent

        if diff_percent <= args.min_still_percent:
            stable_count += 1
            motion_count = 0
            candidate_orig = orig
            candidate_gray = gray
            candidate_time = frame_time
            candidate_frame_index = frame_index

            if stable_count >= args.min_still_frames and not stable_segment_saved:
                is_new_scene = True
                if last_saved_gray is not None and candidate_gray is not None:
                    delta = frame_change_percent(
                        last_saved_gray,
                        candidate_gray,
                        args.dedupe_pixel_threshold,
                    )
                    is_new_scene = delta >= args.dedupe_percent

                if is_new_scene and candidate_orig is not None:
                    candidate_mask = extract_content_mask(candidate_gray)

                    replace_previous = False
                    if (
                        args.collapse_monotonic_build
                        and last_saved_mask is not None
                        and last_saved_path is not None
                    ):
                        containment, add_percent, remove_percent = monotonic_growth_stats(
                            last_saved_mask,
                            candidate_mask,
                        )
                        replace_previous = (
                            containment >= args.monotonic_min_containment
                            and add_percent >= args.monotonic_min_add_percent
                            and remove_percent <= args.monotonic_max_remove_percent
                        )

                    target_index = saved_count - 1 if replace_previous and saved_count > 0 else saved_count
                    filename = f"{target_index:03}_{candidate_time:.2f}s.png"
                    path = os.path.join(output_folder_screenshot_path, filename)

                    if replace_previous and saved_count > 0:
                        print(f"replacing {last_saved_path} -> {path}")
                        if os.path.exists(last_saved_path) and last_saved_path != path:
                            os.remove(last_saved_path)
                    else:
                        print(f"saving {path}")

                    cv2.imwrite(path, candidate_orig)
                    last_saved_gray = candidate_gray.copy()
                    last_saved_mask = candidate_mask.copy()
                    last_saved_path = path
                    if not replace_previous:
                        saved_count += 1
                    stable_segment_saved = True

        elif diff_percent >= args.reset_motion_percent:
            motion_count += 1
            stable_count = 0
            if motion_count >= args.reset_frames:
                stable_segment_saved = False
                candidate_orig = None
                candidate_gray = None
        else:
            # 中间区域说明场景处于变化/过渡中，重置稳定计数，
            # 但不立刻允许再次保存，等待明显进入“新稳定段”。
            stable_count = 0
            motion_count = 0

        if args.progress_every > 0 and sample_index % args.progress_every == 0:
            print(
                f"processed={sample_index}, time={frame_time:.1f}s, diff={diff_percent:.3f}%, saved={saved_count}"
            )

    print(f"{saved_count} screenshots captured!")
    print(f"last diff percent: {last_diff_percent}")
    print(f"time taken {time.time() - start_time:.2f}s")


def initialize_output_folder(video_path):
    output_folder_screenshot_path = f"{OUTPUT_SLIDES_DIR}/{os.path.splitext(os.path.basename(video_path))[0]}"
    if os.path.exists(output_folder_screenshot_path):
        shutil.rmtree(output_folder_screenshot_path)
    os.makedirs(output_folder_screenshot_path, exist_ok=True)
    print("initialized output folder", output_folder_screenshot_path)
    return output_folder_screenshot_path


def convert_screenshots_to_pdf(video_path, output_folder_screenshot_path):
    output_pdf_path = f"{OUTPUT_SLIDES_DIR}/{os.path.splitext(os.path.basename(video_path))[0]}.pdf"
    print("output_folder_screenshot_path", output_folder_screenshot_path)
    print("output_pdf_path", output_pdf_path)
    print("converting images to pdf..")
    with open(output_pdf_path, "wb") as file_obj:
        file_obj.write(img2pdf.convert(sorted(glob.glob(f"{output_folder_screenshot_path}/*.png"))))
    print("PDF created!")
    print("pdf saved at", output_pdf_path)


def parse_args():
    parser = argparse.ArgumentParser("video_path")
    parser.add_argument("video_path", help="path of video to be converted to pdf slides", type=str)
    parser.add_argument("--sample-rate", type=float, default=DEFAULT_SAMPLE_RATE, help="frames per second to analyze")
    parser.add_argument("--warmup-seconds", type=float, default=DEFAULT_WARMUP_SECONDS, help="initial seconds to skip")
    parser.add_argument("--history-seconds", type=float, default=DEFAULT_HISTORY_SECONDS, help="background history in sampled seconds")
    parser.add_argument("--var-threshold", type=float, default=DEFAULT_VAR_THRESHOLD, help="MOG2 variance threshold")
    parser.add_argument("--detect-shadows", action="store_true", default=DEFAULT_DETECT_SHADOWS, help="enable MOG2 shadow detection")
    parser.add_argument("--min-still-percent", type=float, default=DEFAULT_MIN_STILL_PERCENT, help="foreground percent below which a scene is considered stable")
    parser.add_argument("--reset-motion-percent", type=float, default=DEFAULT_RESET_MOTION_PERCENT, help="foreground percent above which a new motion segment is recognized")
    parser.add_argument("--min-still-frames", type=int, default=DEFAULT_MIN_STILL_FRAMES, help="consecutive stable sampled frames required before saving")
    parser.add_argument("--reset-frames", type=int, default=DEFAULT_RESET_FRAMES, help="consecutive motion sampled frames required to allow a new save")
    parser.add_argument("--resize-width", type=int, default=DEFAULT_RESIZE_WIDTH, help="working resize width")
    parser.add_argument("--dedupe-percent", type=float, default=DEFAULT_DEDUPE_PERCENT, help="minimum frame difference percent versus last saved slide")
    parser.add_argument("--dedupe-pixel-threshold", type=int, default=DEFAULT_DEDUPE_PIXEL_THRESHOLD, help="pixel diff threshold used for dedupe")
    parser.add_argument(
        "--collapse-monotonic-build",
        action="store_true",
        default=DEFAULT_COLLAPSE_MONOTONIC_BUILD,
        help="when content only grows without real removal, keep only the latest frame in that sequence",
    )
    parser.add_argument(
        "--monotonic-min-add-percent",
        type=float,
        default=DEFAULT_MONOTONIC_MIN_ADD_PERCENT,
        help="minimum newly added content percent required to replace the previous saved frame",
    )
    parser.add_argument(
        "--monotonic-max-remove-percent",
        type=float,
        default=DEFAULT_MONOTONIC_MAX_REMOVE_PERCENT,
        help="maximum removed content percent allowed when collapsing a monotonic build sequence",
    )
    parser.add_argument(
        "--monotonic-min-containment",
        type=float,
        default=DEFAULT_MONOTONIC_MIN_CONTAINMENT,
        help="required containment of the previous saved content inside the new frame for monotonic collapsing",
    )
    parser.add_argument("--progress-every", type=int, default=200, help="progress log interval in sampled frames")
    parser.add_argument("--auto-continue", action="store_true", help="skip manual confirmation and create pdf directly")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    video_path = args.video_path

    print("video_path", video_path)
    output_folder_screenshot_path = initialize_output_folder(video_path)
    detect_unique_screenshots(video_path, output_folder_screenshot_path, args)

    if args.auto_continue:
        convert_screenshots_to_pdf(video_path, output_folder_screenshot_path)
    else:
        print("Please manually verify screenshots and delete duplicates if needed")
        while True:
            choice = input("Press y to continue and n to terminate").lower().strip()
            if choice in ["y", "n"]:
                break
            print("please enter a valid choice")

        if choice == "y":
            convert_screenshots_to_pdf(video_path, output_folder_screenshot_path)
