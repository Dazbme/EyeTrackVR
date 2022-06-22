import PySimpleGUI as sg
from config import RansacConfig
from threading import Event, Thread, Lock
from ransac import Ransac, InformationOrigin
from enum import Enum
from queue import Queue, Empty
from camera import Camera
import cv2


class CameraWidgetName(Enum):
    RIGHT_EYE = 0
    LEFT_EYE = 1


class CameraWidget:
    def __init__(
        self,
        widget_id: CameraWidgetName,
        main_config: RansacConfig,
    ):
        self.gui_camera_addr = f"-CAMERAADDR{widget_id}-"
        self.gui_threshold_slider = f"-THREADHOLDSLIDER{widget_id}-"
        self.gui_rotation_slider = f"-ROTATIONSLIDER{widget_id}-"
        self.gui_scalar_slider = f"-EYESCALARSLIDER{widget_id}-"
        self.gui_roi_button = f"-ROIMODE{widget_id}-"
        self.gui_roi_layout = f"-ROILAYOUT{widget_id}-"
        self.gui_roi_selection = f"-GRAPH{widget_id}-"
        self.gui_tracking_button = f"-TRACKINGMODE{widget_id}-"
        self.gui_save_tracking_button = f"-SAVETRACKINGBUTTON{widget_id}-"
        self.gui_tracking_layout = f"-TRACKINGLAYOUT{widget_id}-"
        self.gui_tracking_image = f"-IMAGE{widget_id}-"
        self.gui_output_graph = f"-OUTPUTGRAPH{widget_id}-"
        self.gui_restart_calibration = f"-RESTARTCALIBRATION{widget_id}-"
        self.gui_recenter_eye = f"-RECENTEREYE{widget_id}-"
        self.gui_mode_readout = f"-APPMODE{widget_id}-"
        self.gui_show_color_image = f"-SHOWCOLORIMAGE{widget_id}-"

        self.main_config = main_config
        if widget_id == CameraWidgetName.RIGHT_EYE:
            self.config = main_config.right_eye
        else:
            self.config = main_config.left_eye

        self.roi_layout = [
            [
                sg.Graph(
                    (640, 480),
                    (0, 480),
                    (640, 0),
                    key=self.gui_roi_selection,
                    drag_submits=True,
                    enable_events=True,
                )
            ]
        ]

        # Define the window's contents
        self.tracking_layout = [
            [
                sg.Text("Threshold"),
                sg.Slider(
                    range=(0, 100),
                    default_value=self.config.threshold,
                    orientation="h",
                    key=self.gui_threshold_slider,
                ),
            ],
            [
                sg.Text("Rotation"),
                sg.Slider(
                    range=(0, 360),
                    default_value=self.config.rotation_angle,
                    orientation="h",
                    key=self.gui_rotation_slider,
                ),
            ],
            [
                sg.Text("Eye Position Scalar"),
                sg.Slider(
                    range=(0, 5000),
                    default_value=self.config.vrc_eye_position_scalar,
                    orientation="h",
                    key=self.gui_scalar_slider,
                ),
            ],
            [
                sg.Button("Restart Calibration", key=self.gui_restart_calibration),
                sg.Button("Recenter Eye", key=self.gui_recenter_eye),
                sg.Checkbox(
                    "Show Color Image:",
                    default=self.config.show_color_image,
                    key=self.gui_show_color_image,
                ),
            ],
            [sg.Text("Mode:"), sg.Text("Calibrating", key=self.gui_mode_readout)],
            [sg.Image(filename="", key=self.gui_tracking_image)],
            [
                sg.Graph(
                    (200, 200),
                    (-100, 100),
                    (100, -100),
                    background_color="white",
                    key=self.gui_output_graph,
                    drag_submits=True,
                    enable_events=True,
                )
            ],
        ]

        self.widget_layout = [
            [
                sg.Text("Camera Address"),
                sg.InputText(self.config.capture_source, key=self.gui_camera_addr),
            ],
            [
                sg.Button(
                    "Save and Restart Tracking", key=self.gui_save_tracking_button
                ),
            ],
            [
                sg.Button("Tracking Mode", key=self.gui_tracking_button),
                sg.Button("ROI Mode", key=self.gui_roi_button),
            ],
            [
                sg.Column(self.tracking_layout, key=self.gui_tracking_layout),
                sg.Column(self.roi_layout, key=self.gui_roi_layout, visible=False),
            ],
        ]

        self.cancellation_event = Event()
        self.capture_event = Event()
        self.capture_queue = Queue()
        self.roi_queue = Queue()

        self.image_queue = Queue()

        self.ransac = Ransac(
            self.config,
            self.cancellation_event,
            self.capture_event,
            self.capture_queue,
            self.image_queue,
        )
        self.ransac_thread = Thread(target=self.ransac.run)
        self.ransac_thread.start()

        self.camera_status_queue = Queue()
        self.camera = Camera(
            self.config,
            0,
            self.cancellation_event,
            self.capture_event,
            self.camera_status_queue,
            self.capture_queue,
        )

        self.camera_thread = Thread(target=self.camera.run)
        self.camera_thread.start()

        self.x0, self.y0 = None, None
        self.x1, self.y1 = None, None
        self.figure = None
        self.is_mouse_up = True
        self.in_roi_mode = False

    def shutdown(self):
        self.cancellation_event.set()
        self.ransac_thread.join()
        self.camera_thread.join()

    def render(self, window, event, values):

        changed = False
        # If anything has changed in our configuration settings, change/update those.
        if (
            event == self.gui_save_tracking_button
            and values[self.gui_camera_addr] != self.config.capture_source
        ):
            print("New value: {}".format(values[self.gui_camera_addr]))
            try:
                # Try storing ints as ints, for those using wired cameras.
                self.config.capture_source = int(values[self.gui_camera_addr])
            except ValueError:
                if values[self.gui_camera_addr] == "":
                    self.config.capture_source = None
                else:
                    self.config.capture_source = values[self.gui_camera_addr]
            changed = True

        if self.config.threshold != values[self.gui_threshold_slider]:
            self.config.threshold = int(values[self.gui_threshold_slider])
            changed = True

        if self.config.rotation_angle != values[self.gui_rotation_slider]:
            self.config.rotation_angle = int(values[self.gui_rotation_slider])
            changed = True

        if self.config.vrc_eye_position_scalar != values[self.gui_scalar_slider]:
            self.config.vrc_eye_position_scalar = int(values[self.gui_scalar_slider])
            changed = True

        if self.config.show_color_image != values[self.gui_show_color_image]:
            self.config.show_color_image = values[self.gui_show_color_image]
            changed = True

        if changed:
            self.main_config.save()

        if event == self.gui_tracking_button:
            print("Moving to tracking mode")
            self.in_roi_mode = False
            self.camera.set_output_queue(self.capture_queue)
            window[self.gui_roi_layout].update(visible=False)
            window[self.gui_tracking_layout].update(visible=True)
        elif event == self.gui_roi_button:
            print("move to roi mode")
            self.in_roi_mode = True
            self.camera.set_output_queue(self.roi_queue)
            window[self.gui_roi_layout].update(visible=True)
            window[self.gui_tracking_layout].update(visible=False)
        elif event == "{}+UP".format(self.gui_roi_selection):
            # Event for mouse button up in ROI mode
            self.is_mouse_up = True
            if abs(self.x0 - self.x1) != 0 and abs(self.y0 - self.y1) != 0:
                self.config.roi_window_x = min([self.x0, self.x1])
                self.config.roi_window_y = min([self.y0, self.y1])
                self.config.roi_window_w = abs(self.x0 - self.x1)
                self.config.roi_window_h = abs(self.y0 - self.y1)
                self.main_config.save()
        elif event == self.gui_roi_selection:
            # Event for mouse button down or mouse drag in ROI mode
            if self.is_mouse_up:
                self.is_mouse_up = False
                self.x0, self.y0 = values[self.gui_roi_selection]
            self.x1, self.y1 = values[self.gui_roi_selection]
        elif event == self.gui_restart_calibration:
            self.ransac.calibration_frame_counter = 300
        elif event == self.gui_recenter_eye:
            self.ransac.recenter_eye = True

        if self.ransac.calibration_frame_counter != None:
            window[self.gui_mode_readout].update("Calibration")
        else:
            window[self.gui_mode_readout].update("Tracking")

        if self.in_roi_mode:
            try:
                if self.roi_queue.empty():
                    self.capture_event.set()
                maybe_image = self.roi_queue.get(block=False)
                imgbytes = cv2.imencode(".ppm", maybe_image[0])[1].tobytes()
                graph = window[self.gui_roi_selection]
                if self.figure:
                    graph.delete_figure(self.figure)
                # INCREDIBLY IMPORTANT ERASE. Drawing images does NOT overwrite the buffer, the fucking
                # graph keeps every image fed in until you call this. Therefore we have to make sure we
                # erase before we redraw, otherwise we'll leak memory *very* quickly.
                graph.erase()
                graph.draw_image(data=imgbytes, location=(0, 0))
                if None not in (self.x0, self.y0, self.x1, self.y1):
                    self.figure = graph.draw_rectangle(
                        (self.x0, self.y0), (self.x1, self.y1), line_color="blue"
                    )
            except Empty:
                pass
        else:
            try:
                (maybe_image, eye_info) = self.image_queue.get(block=False)
                imgbytes = cv2.imencode(".ppm", maybe_image)[1].tobytes()
                window[self.gui_tracking_image].update(data=imgbytes)

                # Update the GUI
                graph = window[self.gui_output_graph]
                graph.erase()

                if (
                    eye_info.info_type != InformationOrigin.FAILURE
                    and not eye_info.blink
                ):
                    graph.update(background_color="white")
                    graph.draw_circle(
                        (eye_info.x * -100, eye_info.y * -100),
                        25,
                        fill_color="black",
                        line_color="white",
                    )
                elif eye_info.blink:
                    graph.update(background_color="blue")
                elif eye_info.info_type == InformationOrigin.FAILURE:
                    graph.update(background_color="red")

                # Relay information to OSC
                # if eye_info.info_type != InformationOrigin.FAILURE:
                #     osc_put(eye_info)
            except Empty:
                pass
        pass
