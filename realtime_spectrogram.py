# --- Necessary Imports ---
import sys
import platform
import time
import traceback
import warnings
import numpy as np
from scipy.signal import get_window
import soundcard as sc
import pyqtgraph as pg
from PyQt6 import QtWidgets, QtCore, QtGui
import matplotlib # Import base library
import matplotlib.cm

# --- Configuration Constants ---
DEFAULT_SAMPLE_RATE = 44100; DEFAULT_CHUNK_SIZE = 1024 * 2; DEFAULT_N_FFT = DEFAULT_CHUNK_SIZE
DEFAULT_FREQ_SCALE = 'Logarithmic'; DEFAULT_COLORMAP = 'viridis'; DEFAULT_VERBOSE_CONSOLE = False
DEFAULT_SUPPRESS_WARNINGS = True; DEFAULT_SPEC_DB_MIN = -70.0; DEFAULT_SPEC_DB_MAX = 10.0
DEFAULT_RESP_HEADROOM = 10.0;
WINDOW_TYPE = 'hann'; HISTORY_SECONDS = 10.0; PLOT_FREQ_MIN_HZ = 10
# *** Added Timer Interval ***
UPDATE_INTERVAL_MS = 40  # Approx 25 FPS for GUI updates

SUPPORTED_SAMPLE_RATES = [8000, 11025, 16000, 22050, 32000, 44100, 48000, 88200, 96000]
SUPPORTED_FFT_SIZES = [512, 1024, 2048, 4096, 8192, 16384]
# User preferred list
SUPPORTED_COLORMAPS = ['cividis', 'inferno', 'magma', 'plasma', 'turbo', 'viridis']

# --- Globals ---
main_window = None

# --- Warning Filtering ---
def update_warning_filter(suppress):
    # ... (function unchanged) ...
    action = "ignore" if suppress else "default"; warnings.filterwarnings(action, message=".*data discontinuity.*")
    status = "suppressed" if suppress else "enabled"; verbose = DEFAULT_VERBOSE_CONSOLE
    if main_window is not None and hasattr(main_window, 'verbose_console'): verbose = main_window.verbose_console
    if verbose: print(f"Soundcard discontinuity warnings {status}.")


# --- Error Reporting ---
def show_qt_error(title, message): # ... (unchanged) ...
    tb_str = traceback.format_exc(); print(f"\n--- APPLICATION ERROR (FATAL) ---\n", file=sys.stderr); print(f"Title: {title}", file=sys.stderr); print(f"Message: {message}", file=sys.stderr); print(f"Traceback:\n{tb_str}", file=sys.stderr); print(f"--- END ERROR ---", file=sys.stderr)
    app = QtWidgets.QApplication.instance();
    if app is None: app = QtWidgets.QApplication([sys.executable])
    msg_box = QtWidgets.QMessageBox(); msg_box.setIcon(QtWidgets.QMessageBox.Icon.Critical); msg_box.setWindowTitle(title); msg_box.setText(f"{message}\n\nThe application will now exit."); msg_box.setDetailedText(tb_str)
    msg_box.exec(); sys.exit(1)
def show_qt_warning(title, message, details=""): # ... (unchanged) ...
    is_verbose = DEFAULT_VERBOSE_CONSOLE; global main_window
    if main_window is not None and hasattr(main_window, 'verbose_console'): is_verbose = main_window.verbose_console
    if is_verbose: print(f"\n--- APPLICATION WARNING ---\nTitle: {title}\nMessage: {message}", file=sys.stderr)
    if details: print(f"Details:\n{details}", file=sys.stderr)
    if is_verbose: print("--- END WARNING ---", file=sys.stderr)
    app = QtWidgets.QApplication.instance();
    if app is None: app = QtWidgets.QApplication([sys.executable])
    msg_box = QtWidgets.QMessageBox(); msg_box.setIcon(QtWidgets.QMessageBox.Icon.Warning); msg_box.setWindowTitle(title); msg_box.setText(message)
    if details: msg_box.setDetailedText(details); msg_box.exec()

# --- Platform Specific Error Guidance ---
def get_platform_guidance(): # ... (unchanged) ...
    os_name = platform.system(); guidance = "Could not find a suitable audio loopback device.\n\n..."
    return guidance

# --- Loopback Device Detection ---
selected_device = None; actual_sample_rate = DEFAULT_SAMPLE_RATE
def find_loopback_device(): # ... (unchanged) ...
    global selected_device, actual_sample_rate; actual_sample_rate = DEFAULT_SAMPLE_RATE; print("Searching for suitable audio devices...")
    def test_device(device, rate_to_test):
        try:
            verbose_test = DEFAULT_VERBOSE_CONSOLE; global main_window;
            if main_window is not None and hasattr(main_window, 'verbose_console'): verbose_test = main_window.verbose_console
            if verbose_test: print(f"Testing device: {device.name} with {rate_to_test} Hz")
            test_chunk = min(DEFAULT_CHUNK_SIZE, 1024)
            with device.recorder(samplerate=rate_to_test, channels=device.channels, blocksize=test_chunk) as r:
                if r is None: print(f"Failed to create recorder for {device.name}"); return False
                test_data = r.record(numframes=test_chunk // 4)
            if test_data is not None and test_data.shape[0] > 0:
                 if verbose_test: print(f"Device {device.name} test successful at {rate_to_test} Hz.")
                 return True
            else: print(f"Device {device.name} test record returned no data or failed."); return False
        except AttributeError as ae:
             if hasattr(sc.platform, 'windows') and 'recorder' in str(ae) and isinstance(device, sc.platform.windows.mediafoundation._Speaker): print(f"Ignoring AttributeError: {ae} for Speaker object (known issue)."); return False
             else: print(f"Test failed for {device.name} with AttributeError: {ae}"); return False
        except Exception as e:
            if "unsupported sample rate" in str(e).lower(): print(f"Rate {rate_to_test}Hz not supported by {device.name}.")
            else: print(f"Test failed for {device.name} at {rate_to_test} Hz: {type(e).__name__}: {e}")
            return False
    found = False
    try:
        default_speaker = sc.default_speaker(); print(f"Checking default speaker: {default_speaker.name} (Channels: {default_speaker.channels})")
        if default_speaker.channels >= 2 and test_device(default_speaker, DEFAULT_SAMPLE_RATE): print(f"Default speaker '{default_speaker.name}' usable at default rate."); selected_device = default_speaker; actual_sample_rate = DEFAULT_SAMPLE_RATE; found = True
    except Exception as e: print(f"Error accessing/testing default speaker: {e}")
    if not found:
        print("Searching explicit loopback devices...")
        try:
            mics = sc.all_microphones(include_loopback=True)
            candidates = {m.id: m for m in mics if m.isloopback or any(k in m.name for k in ["Loopback", "Stereo Mix", "What U Hear", "Monitor of"])}
            if candidates:
                print(f"Found {len(candidates)} potential loopback candidate(s). Testing...")
                tested_devices = set()
                for dev_id, lb in candidates.items():
                     if lb.id in tested_devices: continue; tested_devices.add(lb.id)
                     if lb.channels >= 2 and test_device(lb, DEFAULT_SAMPLE_RATE): print(f"Selecting stereo loopback device: {lb.name}"); selected_device = lb; actual_sample_rate = DEFAULT_SAMPLE_RATE; found = True; break
                     elif not found and lb.channels >=1 and test_device(lb, DEFAULT_SAMPLE_RATE):
                         print(f"Selecting mono loopback device: {lb.name}")
                         show_qt_warning("Mono Loopback", f"Using mono loopback device: {lb.name}.\nVisualization will duplicate the mono channel.")
                         selected_device = lb; actual_sample_rate = DEFAULT_SAMPLE_RATE; found = True; break
                if not found: print("None of the candidates worked at the default sample rate.")
            else: print("No devices explicitly marked or named as loopback found.")
        except Exception as e: print(f"Error searching/testing microphones: {e}")
    if not found or selected_device is None: error_message = get_platform_guidance(); show_qt_error("Audio Loopback Error", error_message)
    print(f"Selected device: {selected_device.name} at {actual_sample_rate} Hz")
    return selected_device

# --- Audio Processing Thread (Added Error Signal) ---
class AudioProcessor(QtCore.QThread):
    newData = QtCore.pyqtSignal(dict); finished = QtCore.pyqtSignal(); errorOccurred = QtCore.pyqtSignal(str)
    def __init__(self, device, sample_rate, chunk_size, n_fft, window): super().__init__(); self.device = device; self.sample_rate = sample_rate; self.chunk_size = chunk_size; self.n_fft = n_fft; self.window = window; self._is_running = False; self.recorder = None; self.num_channels = device.channels
    def run(self):
        self._is_running = True; verbose = DEFAULT_VERBOSE_CONSOLE; global main_window
        if main_window is not None and hasattr(main_window, 'verbose_console'): verbose = main_window.verbose_console
        if verbose: print(f"AudioProcessor thread started (Rate: {self.sample_rate}, Chunk: {self.chunk_size}, FFT: {self.n_fft}).")
        try:
            with self.device.recorder(samplerate=self.sample_rate, channels=self.num_channels, blocksize=self.chunk_size) as self.recorder:
                if self.recorder is None: raise RuntimeError("Failed to create recorder object in thread.")
                if verbose: print(f"Recorder created: {self.recorder}")
                while self._is_running:
                    data = self.recorder.record(numframes=self.chunk_size)
                    if not self._is_running: break
                    if data is None or data.shape[0] < self.chunk_size: time.sleep(0.005); continue
                    if self.num_channels >= 2: audio_L, audio_R = data[:, 0], data[:, 1]
                    else: audio_L = audio_R = data[:, 0]
                    windowed_L = audio_L * self.window; fft_L = np.fft.rfft(windowed_L, n=self.n_fft); magnitude_L = np.abs(fft_L); db_magnitude_L = 20 * np.log10(magnitude_L + 1e-9)
                    windowed_R = audio_R * self.window; fft_R = np.fft.rfft(windowed_R, n=self.n_fft); magnitude_R = np.abs(fft_R); db_magnitude_R = 20 * np.log10(magnitude_R + 1e-9)
                    processed_data = {'db_L': db_magnitude_L,'db_R': db_magnitude_R}
                    if self._is_running: self.newData.emit(processed_data)
        except Exception as e:
            error_msg = f"Error in AudioProcessor run loop: {type(e).__name__}: {e}"; print(error_msg, file=sys.stderr); traceback.print_exc(file=sys.stderr)
            if self._is_running: self.errorOccurred.emit(error_msg)
        finally: print("AudioProcessor thread finished."); self._is_running = False; self.finished.emit()
    def stop(self): print("AudioProcessor stop requested."); self._is_running = False

# --- Configuration Dialog ---
class ConfigDialog(QtWidgets.QDialog):
    # ... (class unchanged) ...
    def __init__(self, current_settings, parent=None):
        super().__init__(parent); self.setWindowTitle("Configuration"); self.layout = QtWidgets.QVBoxLayout(self); self.formLayout = QtWidgets.QFormLayout(); self.current_settings = current_settings
        self.sampleRateCombo = QtWidgets.QComboBox(); self.sampleRateCombo.addItems([str(rate) for rate in SUPPORTED_SAMPLE_RATES]); self.sampleRateCombo.setCurrentText(str(current_settings.get('sample_rate', DEFAULT_SAMPLE_RATE))); self.formLayout.addRow("Sample Rate (Hz):", self.sampleRateCombo)
        self.fftSizeCombo = QtWidgets.QComboBox(); self.fftSizeCombo.addItems([str(size) for size in SUPPORTED_FFT_SIZES]); self.fftSizeCombo.setCurrentText(str(current_settings.get('fft_size', DEFAULT_N_FFT))); self.formLayout.addRow("FFT Size (Points):", self.fftSizeCombo)
        self.freqScaleGroup = QtWidgets.QButtonGroup(self); self.linRadio = QtWidgets.QRadioButton("Linear"); self.logRadio = QtWidgets.QRadioButton("Logarithmic"); self.freqScaleGroup.addButton(self.linRadio); self.freqScaleGroup.addButton(self.logRadio); scaleLayout = QtWidgets.QHBoxLayout(); scaleLayout.addWidget(self.linRadio); scaleLayout.addWidget(self.logRadio)
        if current_settings.get('freq_scale', DEFAULT_FREQ_SCALE) == 'Linear': self.linRadio.setChecked(True)
        else: self.logRadio.setChecked(True)
        self.formLayout.addRow("Spectrogram Freq. Scale:", scaleLayout)
        self.colormapCombo = QtWidgets.QComboBox(); self.colormapCombo.addItems(SUPPORTED_COLORMAPS); self.colormapCombo.setCurrentText(current_settings.get('colormap', DEFAULT_COLORMAP)); self.formLayout.addRow("Spectrogram Colormap:", self.colormapCombo)
        self.specMinDbSpin = QtWidgets.QDoubleSpinBox(); self.specMinDbSpin.setRange(-120.0, 0.0); self.specMinDbSpin.setValue(current_settings.get('spec_db_min', DEFAULT_SPEC_DB_MIN)); self.specMinDbSpin.setSingleStep(5.0); self.formLayout.addRow("Spectrogram Min dB:", self.specMinDbSpin)
        self.specMaxDbSpin = QtWidgets.QDoubleSpinBox(); self.specMaxDbSpin.setRange(-30.0, 60.0); self.specMaxDbSpin.setValue(current_settings.get('spec_db_max', DEFAULT_SPEC_DB_MAX)); self.specMaxDbSpin.setSingleStep(5.0); self.formLayout.addRow("Spectrogram Max dB:", self.specMaxDbSpin)
        self.respHeadroomSpin = QtWidgets.QDoubleSpinBox(); self.respHeadroomSpin.setRange(0.0, 60.0); self.respHeadroomSpin.setValue(current_settings.get('resp_headroom', DEFAULT_RESP_HEADROOM)); self.respHeadroomSpin.setSingleStep(1.0); self.formLayout.addRow("Freq. Resp. Headroom (dB):", self.respHeadroomSpin)
        self.verboseCheck = QtWidgets.QCheckBox("Enable Verbose Console Output"); self.verboseCheck.setChecked(current_settings.get('verbose', DEFAULT_VERBOSE_CONSOLE)); self.formLayout.addRow(self.verboseCheck)
        self.suppressWarnCheck = QtWidgets.QCheckBox("Suppress Discontinuity Warnings"); self.suppressWarnCheck.setChecked(current_settings.get('suppress_warnings', DEFAULT_SUPPRESS_WARNINGS)); self.formLayout.addRow(self.suppressWarnCheck)
        self.layout.addLayout(self.formLayout)
        self.buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.buttonBox.accepted.connect(self.accept); self.buttonBox.rejected.connect(self.reject); self.layout.addWidget(self.buttonBox)
    def get_settings(self): # Removed max freq
        freq_scale = 'Logarithmic' if self.logRadio.isChecked() else 'Linear'
        return {'sample_rate': int(self.sampleRateCombo.currentText()), 'fft_size': int(self.fftSizeCombo.currentText()),
                'freq_scale': freq_scale, 'colormap': self.colormapCombo.currentText(),
                'spec_db_min': self.specMinDbSpin.value(), 'spec_db_max': self.specMaxDbSpin.value(),
                'resp_headroom': self.respHeadroomSpin.value(),
                'verbose': self.verboseCheck.isChecked(), 'suppress_warnings': self.suppressWarnCheck.isChecked()}

# --- Custom Axis Class for Hz/kHz Formatting ---
class CustomFreqAxis(pg.AxisItem):
    # ... (class unchanged) ...
    def tickStrings(self, values, scale, spacing):
        strings = [];
        for v in values:
            try: freq = 10**v
            except OverflowError: freq = float('inf')
            if freq < 1000: strings.append(f"{freq:.0f}")
            else: strings.append(f"{freq/1000:.1f}k")
        return strings

# --- Main Application Window ---
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, device):
        super().__init__(); global selected_device, actual_sample_rate, main_window; main_window = self; self.device = selected_device
        self.current_sample_rate = actual_sample_rate; self.current_fft_size = DEFAULT_N_FFT; self.current_chunk_size = DEFAULT_CHUNK_SIZE
        self.current_freq_scale = DEFAULT_FREQ_SCALE; self.current_colormap = DEFAULT_COLORMAP; self.verbose_console = DEFAULT_VERBOSE_CONSOLE
        self.suppress_warnings = DEFAULT_SUPPRESS_WARNINGS; self.current_spec_db_min = DEFAULT_SPEC_DB_MIN; self.current_spec_db_max = DEFAULT_SPEC_DB_MAX
        self.current_resp_headroom = DEFAULT_RESP_HEADROOM;
        self.n_fft = self.current_fft_size; self.num_channels = self.device.channels if self.device else 0
        self.freq_vector = None; self.time_vector = None; self.spec_history_L = None
        self.spec_history_R = None; self.window = None; self.history_frames_actual = 0;
        self.display_mode = 'Spectrogram' # Added state variable
        # *** Variables to store latest data for timer approach ***
        self.latest_db_L = None
        self.latest_db_R = None
        # -------------------------------------------------------
        update_warning_filter(self.suppress_warnings)
        self.setup_gui();
        self.recalculate_vars_and_configure_plots();
        # *** Initialize plot timer ***
        self.plot_timer = QtCore.QTimer()
        # -------------------------
        self.audio_thread = None; self.audio_processor = None
        self.is_audio_running = False; self.update_button_states()

    def setup_gui(self): # Updated to add radio buttons
        self.central_widget = QtWidgets.QWidget(); self.setCentralWidget(self.central_widget); self.main_layout = QtWidgets.QVBoxLayout(self.central_widget)
        self.graph_widget = pg.GraphicsLayoutWidget(); self.main_layout.addWidget(self.graph_widget, stretch=1)
        # *** Add Display Mode Radio Buttons ***
        self.display_mode_layout = QtWidgets.QHBoxLayout()
        self.display_mode_group = QtWidgets.QButtonGroup(self)
        self.spec_radio = QtWidgets.QRadioButton("Spectrogram")
        self.freq_radio = QtWidgets.QRadioButton("Frequency Response")
        self.display_mode_group.addButton(self.spec_radio); self.display_mode_group.addButton(self.freq_radio)
        self.display_mode_layout.addWidget(QtWidgets.QLabel("Display:")); self.display_mode_layout.addWidget(self.spec_radio); self.display_mode_layout.addWidget(self.freq_radio); self.display_mode_layout.addStretch(1)
        self.main_layout.addLayout(self.display_mode_layout) # Add above control buttons
        self.spec_radio.setChecked(True) # Default selection
        self.display_mode_group.buttonToggled.connect(self.update_display_mode) # Connect signal
        # *** END Radio Buttons ***
        # Control Buttons
        self.button_layout = QtWidgets.QHBoxLayout()
        self.startButton = QtWidgets.QPushButton("Start Audio"); self.stopButton = QtWidgets.QPushButton("Stop Audio"); self.configButton = QtWidgets.QPushButton("Configuration...")
        self.button_layout.addWidget(self.startButton); self.button_layout.addWidget(self.stopButton); self.button_layout.addStretch(1); self.button_layout.addWidget(self.configButton)
        self.main_layout.addLayout(self.button_layout)
        # Window Setup & Plot Items...
        self.setWindowTitle(f'Real-time Audio Analysis - {self.device.name if self.device else "No Device"}'); self.setGeometry(100, 100, 1000, 800)
        self.plot_L_spec = self.graph_widget.addPlot(row=0, col=0); self.plot_R_spec = self.graph_widget.addPlot(row=1, col=0)
        self.custom_freq_axis = CustomFreqAxis(orientation='bottom'); self.plot_freq_resp = self.graph_widget.addPlot(row=2, col=0, axisItems={'bottom': self.custom_freq_axis})
        self.hist_L = pg.HistogramLUTItem(); self.graph_widget.addItem(self.hist_L, row=0, col=1); self.hist_R = pg.HistogramLUTItem(); self.graph_widget.addItem(self.hist_R, row=1, col=1)
        self.img_L = pg.ImageItem(); self.plot_L_spec.addItem(self.img_L); self.hist_L.setImageItem(self.img_L); self.img_R = pg.ImageItem(); self.plot_R_spec.addItem(self.img_R); self.hist_R.setImageItem(self.img_R)
        self.curve_L = self.plot_freq_resp.plot(pen='b', name='Left'); self.curve_R = self.plot_freq_resp.plot(pen='r', name='Right')
        # Connect Control Buttons
        self.startButton.clicked.connect(self.start_audio); self.stopButton.clicked.connect(self.stop_audio); self.configButton.clicked.connect(self.open_config_dialog)
        # Set initial visibility based on default mode
        self.update_display_mode()

    # --- Slot to handle display mode change ---
    @QtCore.pyqtSlot(QtWidgets.QAbstractButton, bool)
    def update_display_mode(self, button=None, checked=False):
        if button is None: show_spectrogram = self.spec_radio.isChecked()
        elif checked: show_spectrogram = (button == self.spec_radio)
        else: return # Ignore unchecked signal
        self.display_mode = 'Spectrogram' if show_spectrogram else 'FrequencyResponse'
        self.print_verbose(f"Display mode set to: {self.display_mode}")
        # Update plot visibility
        self.plot_L_spec.setVisible(show_spectrogram); self.plot_R_spec.setVisible(show_spectrogram)
        self.hist_L.setVisible(show_spectrogram); self.hist_R.setVisible(show_spectrogram)
        self.plot_freq_resp.setVisible(not show_spectrogram)
    # --------------------------------------

    def print_verbose(self, *args, **kwargs): 
        if self.verbose_console: print(*args, **kwargs)

    # --- recalculate_vars_and_configure_plots using HISTORY_SECONDS ---
    def recalculate_vars_and_configure_plots(self):
        # ... (Function unchanged - uses HISTORY_SECONDS) ...
        self.print_verbose(f"Recalculating for Rate: {self.current_sample_rate}, FFT: {self.n_fft}")
        try:
            if self.current_sample_rate <= 0 or self.current_chunk_size <= 0: raise ValueError("Sample rate and chunk size must be positive.")
            self.freq_vector = np.fft.rfftfreq(self.n_fft, 1.0 / self.current_sample_rate)
            self.history_frames_actual = max(1, int(np.ceil(HISTORY_SECONDS * self.current_sample_rate / self.current_chunk_size)))
            self.print_verbose(f"  -> History frames: {self.history_frames_actual} for {HISTORY_SECONDS}s")
            self.time_vector = np.linspace(-HISTORY_SECONDS, 0, self.history_frames_actual)
            spec_data_shape = (len(self.freq_vector), self.history_frames_actual)
            self.spec_history_L = np.full(spec_data_shape, self.current_spec_db_min); self.spec_history_R = np.full(spec_data_shape, self.current_spec_db_min)
            self.window = get_window(WINDOW_TYPE, self.current_chunk_size); self.configure_plots()
        except Exception as e: show_qt_error("Calculation Error", f"Failed during recalculation/plot configuration:\n{e}")

    # --- configure_plots (Unchanged - handles colormaps, fixed time) ---
    def configure_plots(self):
        # ... (Function unchanged - handles colormaps, fixed time axis, legend) ...
        if self.freq_vector is None or self.time_vector is None: self.print_verbose("Error: Vectors not calculated..."); return
        plot_freq_max = self.current_sample_rate / 2; plot_freq_min = max(PLOT_FREQ_MIN_HZ, self.freq_vector[1] if len(self.freq_vector) > 1 else 0); safe_plot_freq_min = max(plot_freq_min, 1e-6)
        is_log_scale = (self.current_freq_scale == 'Logarithmic'); cmap = None; self.print_verbose(f"Attempting to load colormap: '{self.current_colormap}'")
        try: cmap = pg.colormap.get(self.current_colormap); self.print_verbose(f"-> Success using pg.colormap.get()")
        except ValueError:
            self.print_verbose(f"-> Failed pg.colormap.get(), trying matplotlib...")
            try:
                if 'matplotlib.cm' not in sys.modules: self.print_verbose("   -> Error: matplotlib.cm not imported."); raise ImportError
                cmap = pg.colormap.getFromMatplotlib(self.current_colormap); self.print_verbose(f"-> Success using pg.colormap.getFromMatplotlib()")
            except ImportError: self.print_verbose("   -> Matplotlib not installed or import failed."); cmap = pg.colormap.get('viridis'); self.print_verbose("   -> Falling back to 'viridis'.")
            except ValueError: self.print_verbose(f"   -> Colormap '{self.current_colormap}' not found via getFromMatplotlib."); cmap = pg.colormap.get('viridis'); self.print_verbose("   -> Falling back to 'viridis'.")
            except Exception as e: self.print_verbose(f"   -> Error getting colormap via matplotlib: {e}."); cmap = pg.colormap.get('viridis'); self.print_verbose("   -> Falling back to 'viridis'.")
        except Exception as e: self.print_verbose(f"-> Error during initial pg.colormap.get(): {e}."); cmap = pg.colormap.get('viridis'); self.print_verbose("   -> Falling back to 'viridis'.")
        if cmap is None: self.print_verbose("Error: Colormap object is None after checks. Using 'viridis'."); cmap = pg.colormap.get('viridis')
        for plot, img, hist in [(self.plot_L_spec, self.img_L, self.hist_L), (self.plot_R_spec, self.img_R, self.hist_R)]:
            plot.setTitle(f"{'Left' if plot == self.plot_L_spec else 'Right'} Channel Spectrogram"); plot.setLabel('left', 'Frequency', units='Hz'); plot.setLabel('bottom', 'Time', units='s')
            plot.setLogMode(x=False, y=is_log_scale); y_min_plot = np.log10(safe_plot_freq_min) if is_log_scale else plot_freq_min; y_max_plot = np.log10(plot_freq_max) if is_log_scale else plot_freq_max
            plot.setYRange(y_min_plot, y_max_plot); plot.setXRange(-HISTORY_SECONDS, 0)
            tr = QtGui.QTransform(); freq_span_plot = y_max_plot - y_min_plot; time_span = HISTORY_SECONDS; tr.translate(-HISTORY_SECONDS, y_min_plot)
            if self.history_frames_actual > 0 and len(self.freq_vector) > 0 and time_span > 0 and freq_span_plot > 0: tr.scale(time_span / self.history_frames_actual, freq_span_plot / len(self.freq_vector))
            else: self.print_verbose("Warning: Cannot set image transform.")
            img.setTransform(tr); gradient_item = hist.gradient; gradient_item.setColorMap(cmap); hist.setLevels(self.current_spec_db_min, self.current_spec_db_max)
        self.plot_freq_resp.setTitle("Instantaneous Frequency Response"); self.plot_freq_resp.setLabel('left', 'Magnitude', units='dBFS');
        self.plot_freq_resp.setLogMode(x=True, y=False); self.plot_freq_resp.setXRange(np.log10(safe_plot_freq_min), np.log10(plot_freq_max)); resp_y_min = self.current_spec_db_min; resp_y_max = self.current_spec_db_max + self.current_resp_headroom
        self.plot_freq_resp.setYRange(resp_y_min, resp_y_max)
        if self.plot_freq_resp.legend is not None:
            try: vb = self.plot_freq_resp.getViewBox(); vb.removeItem(self.plot_freq_resp.legend)
            except Exception as leg_e: self.print_verbose(f"Note: Could not remove legend item cleanly: {leg_e}"); self.plot_freq_resp.legend.hide()
        self.plot_freq_resp.addLegend(offset=(-10, 10)); self.plot_freq_resp.showGrid(x=True, y=True, alpha=0.5)
        if self.freq_vector is not None: self.curve_L.setData(self.freq_vector, np.full(len(self.freq_vector), self.current_spec_db_min)); self.curve_R.setData(self.freq_vector, np.full(len(self.freq_vector), self.current_spec_db_min))

    # --- START/STOP/HANDLER METHODS (Updated Start/Stop for Timer) ---
    def start_audio(self):
        if self.is_audio_running: self.print_verbose("Audio is already running."); return
        if not self.device: show_qt_warning("Audio Error", "No audio device selected."); return
        self.print_verbose("Starting audio..."); self.audio_processor = None; self.audio_thread = None; self.window = get_window(WINDOW_TYPE, self.current_chunk_size)
        if self.window is None: show_qt_error("Error", f"Failed to create FFT window: {WINDOW_TYPE}"); return

        # Clear latest data buffers when starting
        self.latest_db_L = None
        self.latest_db_R = None

        self.audio_processor = AudioProcessor(self.device, self.current_sample_rate, self.current_chunk_size, self.n_fft, self.window)
        self.audio_thread = QtCore.QThread()
        self.audio_processor.moveToThread(self.audio_thread)
        # *** Connect newData to handler, not directly to update_plots ***
        self.audio_processor.newData.connect(self.handle_new_data)
        # -------------------------------------------------------------
        self.audio_thread.started.connect(self.audio_processor.run); self.audio_processor.finished.connect(self.handle_audio_finished)
        self.audio_processor.errorOccurred.connect(self.handle_audio_error) # Connect error signal
        # *** Connect and start plot timer ***
        self.plot_timer.timeout.connect(self.update_plots)
        self.plot_timer.start(UPDATE_INTERVAL_MS)
        # ---------------------------------
        self.is_audio_running = True; self.update_button_states(); self.audio_thread.start(); self.print_verbose("Audio thread start requested.")

    def stop_audio(self):
        self.print_verbose("Stop audio requested.")
        # *** Stop plot timer ***
        if hasattr(self, 'plot_timer') and self.plot_timer.isActive():
            self.plot_timer.stop()
        # -----------------------
        if not self.is_audio_running or self.audio_processor is None: self.print_verbose("Audio is not running or processor is already None."); self.is_audio_running = False; self.update_button_states(); return
        self.print_verbose("Signalling processor object to stop."); self.audio_processor.stop()
        if self.audio_thread and self.audio_thread.isRunning(): self.print_verbose("Requesting audio thread quit."); self.audio_thread.quit()
        else: self.print_verbose("Audio thread not running or already quit.")

    def handle_audio_finished(self): # Unchanged
        self.print_verbose("Audio processor finished signal received.")
        if self.plot_timer.isActive(): self.plot_timer.stop() # Ensure timer stops if thread finishes unexpectedly
        if self.audio_processor: self.print_verbose("Deleting audio processor object later..."); self.audio_processor.deleteLater(); self.audio_processor = None
        if self.audio_thread:
             self.print_verbose("Deleting audio thread object later...")
             if self.audio_thread.isRunning(): self.print_verbose("Warning: handle_audio_finished called but QThread still running? Quitting again..."); self.audio_thread.quit(); QtCore.QTimer.singleShot(100, self.audio_thread.wait)
             self.audio_thread.deleteLater(); self.audio_thread = None
        self.is_audio_running = False; self.update_button_states(); self.print_verbose("Audio state updated: stopped.")

    @QtCore.pyqtSlot(str)
    def handle_audio_error(self, error_message): # Unchanged
        self.print_verbose(f"Received error from audio thread: {error_message}")
        show_qt_warning("Audio Processing Error", f"An error occurred in the audio processing thread (device may have changed or stopped):\n{error_message}\n\nThe audio stream will be stopped.", details=traceback.format_exc())
        if self.is_audio_running: QtCore.QTimer.singleShot(0, self.stop_audio)
        else: self.is_audio_running = False; self.update_button_states()

    # *** NEW Slot to handle data from audio thread ***
    @QtCore.pyqtSlot(dict)
    def handle_new_data(self, processed_data):
        """Stores the latest processed data."""
        self.latest_db_L = processed_data['db_L']
        self.latest_db_R = processed_data['db_R']
    # ----------------------------------------------

    # *** update_plots now called by timer, uses stored data ***
    def update_plots(self):
        """Updates plot items based on display mode using latest stored data."""
        # Check if data has arrived yet
        if self.latest_db_L is None or self.latest_db_R is None:
            return

        try:
            # Use self.latest_db_L and self.latest_db_R
            db_L = self.latest_db_L
            db_R = self.latest_db_R

            if self.display_mode == 'Spectrogram':
                db_L_clipped = np.clip(db_L, self.current_spec_db_min, self.current_spec_db_max)
                db_R_clipped = np.clip(db_R, self.current_spec_db_min, self.current_spec_db_max)
                if self.spec_history_L is None or self.spec_history_L.shape[1] != self.history_frames_actual: self.print_verbose(f"Warning: History buffer mismatch..."); self.recalculate_vars_and_configure_plots(); return
                self.spec_history_L = np.roll(self.spec_history_L, -1, axis=1); self.spec_history_R = np.roll(self.spec_history_R, -1, axis=1); self.spec_history_L[:, -1] = db_L_clipped; self.spec_history_R[:, -1] = db_R_clipped
                self.img_L.setImage(self.spec_history_L.T, autoLevels=False)
                self.img_R.setImage(self.spec_history_R.T, autoLevels=False)
            elif self.display_mode == 'FrequencyResponse':
                if self.freq_vector is not None and len(self.freq_vector) == len(db_L):
                     self.curve_L.setData(self.freq_vector, db_L)
                     self.curve_R.setData(self.freq_vector, db_R)
                try: # Dynamic Y range update
                    current_max_db = max(np.max(db_L), np.max(db_R)) if len(db_L)>0 and len(db_R)>0 else self.current_spec_db_min; effective_max = max(current_max_db, self.current_spec_db_max); dynamic_ylim_max = effective_max + self.current_resp_headroom; dynamic_ylim_min = self.current_spec_db_min
                    if dynamic_ylim_max > dynamic_ylim_min: self.plot_freq_resp.setYRange(dynamic_ylim_min, dynamic_ylim_max, padding=0)
                except Exception as e_ylim: self.print_verbose(f" Minor error during dynamic Y lim update: {e_ylim}")

        except Exception as e: self.print_verbose(f"Error during plot update: {type(e).__name__}: {e}", file=sys.stderr)
    # -------------------------------------------------------

    def update_button_states(self): # Unchanged
        self.startButton.setEnabled(not self.is_audio_running); self.stopButton.setEnabled(self.is_audio_running)

    # --- Configuration Handling Methods ---
    def open_config_dialog(self): # Unchanged
        if not hasattr(self, 'current_sample_rate'): show_qt_warning("Warning", "Cannot open config before initialization."); return
        current_settings = {'sample_rate': self.current_sample_rate, 'fft_size': self.current_fft_size, 'freq_scale': self.current_freq_scale, 'colormap': self.current_colormap,
                            'spec_db_min': self.current_spec_db_min, 'spec_db_max': self.current_spec_db_max, 'resp_headroom': self.current_resp_headroom,
                            'verbose': self.verbose_console, 'suppress_warnings': self.suppress_warnings}
        dialog = ConfigDialog(current_settings, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            new_settings = dialog.get_settings(); self.print_verbose(f"Config accepted: {new_settings}")
            restart_required = (new_settings['sample_rate'] != self.current_sample_rate or new_settings['fft_size'] != self.current_fft_size)
            recalc_needed = (restart_required or new_settings['freq_scale'] != self.current_freq_scale or new_settings['colormap'] != self.current_colormap or
                             new_settings['spec_db_min'] != self.current_spec_db_min or new_settings['spec_db_max'] != self.current_spec_db_max or
                             new_settings['resp_headroom'] != self.current_resp_headroom)
            config_changed = any(current_settings.get(key) != new_settings.get(key) for key in current_settings if key in new_settings)
            if not config_changed: self.print_verbose("No configuration changes detected."); return
            proceed = True
            if restart_required:
                reply = QtWidgets.QMessageBox.question(self, 'Restart Audio?', "Changing Sample Rate or FFT Size requires restarting the audio stream.\nProceed?", QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel, QtWidgets.QMessageBox.StandardButton.Cancel)
                if reply == QtWidgets.QMessageBox.StandardButton.Cancel: self.print_verbose("Configuration change cancelled by user."); proceed = False
            if proceed: self.print_verbose("Applying new settings..."); self.apply_settings(new_settings, restart_required, recalc_needed)
        else: self.print_verbose("Config dialog cancelled.")
    def apply_settings(self, new_settings, restart_needed, recalc_needed): # Unchanged
        was_running = self.is_audio_running
        if restart_needed and self.is_audio_running: self.stop_audio(); self.print_verbose("Waiting for audio to stop before applying settings..."); QtCore.QTimer.singleShot(200, lambda: self.finish_apply_settings(new_settings, was_running, restart_needed=True, recalc_needed=recalc_needed))
        else: self.finish_apply_settings(new_settings, was_running, restart_needed=restart_needed, recalc_needed=recalc_needed)
    def finish_apply_settings(self, new_settings, was_running, restart_needed=True, recalc_needed=True): # Unchanged
         self.print_verbose(f"Finishing apply settings (Restart={restart_needed}, Recalc={recalc_needed}, WasRunning={was_running})")
         try: # Apply settings...
             config_changed_in_this_step = False; effective_recalc_needed = False
             if self.current_sample_rate != new_settings.get('sample_rate', self.current_sample_rate): self.current_sample_rate = new_settings['sample_rate']; config_changed_in_this_step = True; effective_recalc_needed = True
             if self.current_fft_size != new_settings.get('fft_size', self.current_fft_size): self.current_fft_size = new_settings['fft_size']; self.n_fft = self.current_fft_size; self.current_chunk_size = self.current_fft_size; config_changed_in_this_step = True; effective_recalc_needed = True
             if self.current_freq_scale != new_settings.get('freq_scale', self.current_freq_scale): self.current_freq_scale = new_settings['freq_scale']; config_changed_in_this_step = True; effective_recalc_needed = True
             if self.current_colormap != new_settings.get('colormap', self.current_colormap): self.current_colormap = new_settings['colormap']; config_changed_in_this_step = True; effective_recalc_needed = True
             if self.current_spec_db_min != new_settings.get('spec_db_min', self.current_spec_db_min): self.current_spec_db_min = new_settings['spec_db_min']; config_changed_in_this_step = True; effective_recalc_needed = True
             if self.current_spec_db_max != new_settings.get('spec_db_max', self.current_spec_db_max): self.current_spec_db_max = new_settings['spec_db_max']; config_changed_in_this_step = True; effective_recalc_needed = True
             if self.current_resp_headroom != new_settings.get('resp_headroom', self.current_resp_headroom): self.current_resp_headroom = new_settings['resp_headroom']; config_changed_in_this_step = True; effective_recalc_needed = True
             if self.verbose_console != new_settings.get('verbose', self.verbose_console): self.verbose_console = new_settings['verbose']; config_changed_in_this_step = True
             if self.suppress_warnings != new_settings.get('suppress_warnings', self.suppress_warnings): self.suppress_warnings = new_settings['suppress_warnings']; update_warning_filter(self.suppress_warnings); config_changed_in_this_step = True
             effective_recalc_needed = (self.current_sample_rate != new_settings.get('sample_rate', self.current_sample_rate) or self.current_fft_size != new_settings.get('fft_size', self.current_fft_size) or
                                       self.current_freq_scale != new_settings.get('freq_scale', self.current_freq_scale) or self.current_colormap != new_settings.get('colormap', self.current_colormap) or
                                       self.current_spec_db_min != new_settings.get('spec_db_min', self.current_spec_db_min) or self.current_spec_db_max != new_settings.get('spec_db_max', self.current_spec_db_max) or
                                       self.current_resp_headroom != new_settings.get('resp_headroom', self.current_resp_headroom) )
             if recalc_needed or effective_recalc_needed: self.print_verbose("Recalculating vars and reconfiguring plots..."); self.recalculate_vars_and_configure_plots()
             elif config_changed_in_this_step: self.print_verbose("Settings changed but no plot reconfigure needed.")
             else: self.print_verbose("No settings actually changed value requiring action in this step.")
             if restart_needed and was_running: self.print_verbose("Restarting audio with new settings..."); QtCore.QTimer.singleShot(50, self.start_audio)
             else: self.update_button_states()
         except Exception as e:
             self.print_verbose(f"Error applying settings: {e}", file=sys.stderr); tb_str = traceback.format_exc()
             show_qt_warning("Configuration Error", f"Failed to apply new settings:\n{type(e).__name__}: {e}\n\nApplication will continue with previous valid settings where possible.", details=tb_str)
             self.update_button_states()
    # ---------------------------------------------------

    def closeEvent(self, event): # Unchanged
        self.print_verbose("Close event received."); self.stop_audio(); start_time = time.time()
        while self.is_audio_running and (time.time() - start_time) < 1.5: QtCore.QCoreApplication.processEvents(); time.sleep(0.05)
        if self.is_audio_running: print("Warning: Audio thread may not have fully stopped on close.")
        event.accept()


# --- Main Execution ---
if __name__ == "__main__":
    print("Script started.")
    try: from ctypes import windll; windll.shcore.SetProcessDpiAwareness(1)
    except Exception as e: print(f"Note: Could not set DPI awareness: {e}")
    print("Finding loopback device..."); device = find_loopback_device()
    if DEFAULT_VERBOSE_CONSOLE: print(f"Device found: {device.name}" if device else "None")
    print("Creating QApplication..."); app = pg.mkQApp("Realtime Spectrogram"); print("QApplication created.")
    main_window = None
    try:
        if DEFAULT_VERBOSE_CONSOLE: print("Creating MainWindow...")
        main_window = MainWindow(device);
        if DEFAULT_VERBOSE_CONSOLE: print("MainWindow created.")
        if DEFAULT_VERBOSE_CONSOLE: print("Showing MainWindow...")
        main_window.show();
        if DEFAULT_VERBOSE_CONSOLE: print("MainWindow shown.")
        if DEFAULT_VERBOSE_CONSOLE: print("Starting audio automatically...")
        main_window.start_audio(); # Auto-start
        if DEFAULT_VERBOSE_CONSOLE: print("Audio start initiated.")
    except Exception as e: show_qt_error("Application Error", f"Failed to initialize main application window or audio:\n{type(e).__name__}: {e}")
    if main_window is not None:
        verbose_main = main_window.verbose_console if hasattr(main_window, 'verbose_console') else DEFAULT_VERBOSE_CONSOLE
        if verbose_main: print("Starting Qt event loop...")
        return_code = app.exec()
        if verbose_main: print(f"Qt event loop finished with code {return_code}.")
        sys.exit(return_code)
    else: print("Exiting because main window creation failed.", file=sys.stderr); sys.exit(1)