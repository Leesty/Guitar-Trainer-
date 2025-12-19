"""
Guitar Trainer Application
A modern practice tracker for guitar exercises with metronome and statistics.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import sys
from datetime import datetime
import json
import winsound
import threading
import time
import pygame
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
import webbrowser
try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None



class ModernGuitarTrainerV2:
    def __init__(self, master):
        self.master = master
        master.title("🎸 Guitar Trainer")
        master.geometry("900x700")
        master.configure(bg='#2c3e50')
        
        # Center window on screen
        master.update_idletasks()
        x = (master.winfo_screenwidth() // 2) - (900 // 2)
        y = (master.winfo_screenheight() // 2) - (700 // 2)
        master.geometry(f"900x700+{x}+{y}")
        
        # Get script directory for file paths - use absolute path to ensure we get the correct directory
        if hasattr(sys, 'frozen'):
            # If running as compiled executable
            self.script_dir = os.path.dirname(sys.executable)
        else:
            # If running as script - use realpath to resolve symlinks
            self.script_dir = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
        
        # Initialize variables
        self.exercises = []
        self.current_exercise = None
        self.timer_running = False
        self.elapsed_time = 0
        self.workout_data = []
        self.data_file = os.path.join(self.script_dir, "Guitar Exercises.md")
        self.metronome_running = False
        self.metronome_bpm = 120
        self.metronome_thread = None
        self.metronome_volume = 0.5
        self.metronome_was_running_before_pause = False  # Flag to track metronome state before pause
        self.exercises_structure_file = os.path.join(self.script_dir, "exercises.json")
        self.exercises_structure = {}
        self.settings_file = os.path.join(self.script_dir, "settings.json")
        self.stale_days = 7
        
        # Initialize pygame for sound
        pygame.mixer.init()
        
        # Load saved data
        self.load_data()
        self.load_exercise_structure()
        self.load_settings()
        self.exercises = self.flatten_exercises()
        
        # Setup styles
        self.setup_styles()
        
        # Create interface
        self.create_widgets()
        
        # Show main screen
        self.show_main_screen()

    def setup_styles(self):
        """Setup styles for modern appearance"""
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Title.TLabel', font=('Helvetica', 24, 'bold'), foreground='#ecf0f1', background='#2c3e50')
        style.configure('Subtitle.TLabel', font=('Helvetica', 14), foreground='#bdc3c7', background='#2c3e50')

    # Helper functions for UI creation
    def _create_button(self, parent, text, bg, command, **kwargs):
        """Create a styled button"""
        defaults = {'font': ('Helvetica', 14, 'bold'), 'fg': 'white', 'relief': 'flat', 'padx': 30, 'pady': 15}
        defaults.update(kwargs)
        btn = tk.Button(parent, text=text, bg=bg, command=command, **defaults)
        btn.pack(pady=kwargs.get('pady', 10))
        return btn

    def _create_label(self, parent, text, **kwargs):
        """Create a styled label"""
        defaults = {'font': ('Helvetica', 10), 'bg': '#2c3e50', 'fg': '#ecf0f1'}
        defaults.update(kwargs)
        return tk.Label(parent, text=text, **defaults)

    def _format_time(self, seconds):
        """Format seconds to MM:SS or HH:MM:SS"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours > 0 else f"{minutes:02d}:{secs:02d}"

    def _parse_time(self, time_str):
        """Parse MM:SS or HH:MM:SS to seconds"""
        parts = time_str.split(':')
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return 0

    def _stop_metronome(self):
        """Stop metronome and update button"""
        self.metronome_running = False
        if hasattr(self, 'metronome_start_btn'):
            try:
                # Check if widget still exists
                self.metronome_start_btn.winfo_exists()
                self.metronome_start_btn.config(text="▶️ Start", bg='#27ae60')
            except (tk.TclError, AttributeError):
                # Widget was destroyed, ignore
                pass

    def _create_exercise_data(self, bpm):
        """Create exercise data dict from current state"""
        time_str = self._format_time(self.elapsed_time - 1)
        return {
            'exercise': self.current_exercise,
            'time': time_str,
            'bpm': bpm,
            'timestamp': datetime.now().isoformat()
        }

    def _save_workout_data(self, bpm):
        """Save workout data and stop metronome"""
        self._stop_metronome()
        if not bpm.isdigit():
            messagebox.showerror("Error", "BPM must be a number!")
            return False
        self.workout_data.append(self._create_exercise_data(bpm))
        self.save_data()
        self.update_total_time_display()
        return True

    def _group_data_by_days(self):
        """Group workout data by days"""
        days_data = {}
        for data in self.workout_data:
            try:
                date = datetime.fromisoformat(data['timestamp']).strftime('%d %B %Y')
                days_data.setdefault(date, []).append(data)
            except Exception:
                continue
        return days_data
    
    def _sort_dates(self, date_strings):
        """Sort date strings by actual date (most recent first)"""
        def date_key(date_str):
            try:
                return datetime.strptime(date_str, '%d %B %Y')
            except:
                return datetime.min
        return sorted(date_strings, key=date_key, reverse=True)

    def _cleanup_drag(self):
        """Cleanup drag operation"""
        if hasattr(self, '_drag_ghost') and self._drag_ghost:
            try:
                self._drag_ghost.destroy()
            except Exception:
                pass
            self._drag_ghost = None
        self._drag_item_id = None
        self._drag_start_time = None
        self._drag_start_xy = None
        try:
            if hasattr(self, 'ex_tree'):
                self.ex_tree.configure(cursor='')
        except Exception:
            pass

    def create_widgets(self):
        """Create all widgets"""
        # Main container
        self.main_container = tk.Frame(self.master, bg='#2c3e50')
        self.main_container.pack(fill='both', expand=True, padx=20, pady=(20, 40))
        
        # Developer info in bottom left corner
        self.developer_label = tk.Label(self.master, 
                                       text="Made by Leesty", 
                                       font=('Helvetica', 10),
                                       bg='#2c3e50', fg='#7f8c8d')
        self.developer_label.place(relx=0.02, rely=0.95, anchor='sw')
        
        # Total workout time in bottom right corner
        self.total_time_label = tk.Label(self.master, 
                                        text="", 
                                        font=('Helvetica', 10, 'bold'),
                                        bg='#2c3e50', fg='#27ae60')
        self.total_time_label.place(relx=0.98, rely=0.95, anchor='se')
        
        # Title
        self.title_label = ttk.Label(self.main_container, 
                                    text="🎸 Guitar Trainer", 
                                    style='Title.TLabel')
        self.title_label.pack(pady=(0, 30))
        
        # Main menu buttons
        self.button_frame = tk.Frame(self.main_container, bg='#2c3e50')
        self.button_frame.pack()
        buttons = [
            ("🎯 New Workout", '#3498db', self.new_workout),
            ("📊 Workout History", '#27ae60', self.view_history),
            ("📝 Manage Exercises", '#f39c12', self.manage_exercises),
            ("⚙️ Settings", '#8e44ad', self.open_settings),
            ("🚪 Exit", '#e74c3c', self.master.quit)
        ]
        for text, bg, cmd in buttons:
            self._create_button(self.button_frame, text, bg, cmd)
        
        # Frames for different screens
        self.exercise_frame = tk.Frame(self.main_container, bg='#34495e')
        self.exercise_frame.configure(relief='raised', bd=2)
        
        self.timer_frame = tk.Frame(self.main_container, bg='#34495e')
        self.timer_frame.configure(relief='raised', bd=2)
        
        self.history_frame = tk.Frame(self.main_container, bg='#34495e')
        self.history_frame.configure(relief='raised', bd=2)
        
        self.exercises_manage_frame = tk.Frame(self.main_container, bg='#34495e')
        self.exercises_manage_frame.configure(relief='raised', bd=2)

    def show_main_screen(self):
        """Show main screen"""
        self.exercise_frame.pack_forget()
        self.timer_frame.pack_forget()
        self.history_frame.pack_forget()
        self.exercises_manage_frame.pack_forget()
        self.button_frame.pack()
        # Update total time display
        self.update_total_time_display()

    # Exercise structure (folder tree + INFO)
    def load_exercise_structure(self):
        """Load exercise structure from JSON file. Initialize empty if file doesn't exist."""
        if os.path.exists(self.exercises_structure_file):
            try:
                with open(self.exercises_structure_file, 'r', encoding='utf-8') as f:
                    self.exercises_structure = json.load(f)
                    # Ensure keys exist
                    if 'folders' not in self.exercises_structure:
                        self.exercises_structure['folders'] = {}
                    if 'root' not in self.exercises_structure:
                        self.exercises_structure['root'] = []
                    if 'info' not in self.exercises_structure:
                        self.exercises_structure['info'] = {}
            except Exception:
                self.exercises_structure = {"folders": {}, "root": [], "info": {}}
        else:
            # Initialize empty structure if file doesn't exist
            self.exercises_structure = {"folders": {}, "root": [], "info": {}}
            self.save_exercise_structure()

    # Settings
    def load_settings(self):
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.stale_days = int(data.get('stale_days', 7))
            else:
                self.save_settings()
        except Exception:
            self.stale_days = 7

    def save_settings(self):
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump({'stale_days': self.stale_days}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def save_exercise_structure(self):
        """Save exercise structure to JSON file."""
        with open(self.exercises_structure_file, 'w', encoding='utf-8') as f:
            json.dump(self.exercises_structure, f, ensure_ascii=False, indent=2)

    def flatten_exercises(self):
        """Get all exercise names from structure"""
        names = set(self.exercises_structure.get("root", []))
        for items in self.exercises_structure.get("folders", {}).values():
            names.update(items)
        return sorted(names)

    def new_workout(self):
        """Start new workout"""
        if not self.exercises:
            messagebox.showwarning("Warning", "Exercise list is empty! Add exercises in the menu 'Manage Exercises'.")
            return
        
        self.show_exercise_popup()

    def show_exercise_popup(self):
        """Show exercise selection popup with folders and statistics"""
        popup = tk.Toplevel(self.master)
        popup.title("Select Exercise")
        popup.geometry("700x700")
        popup.configure(bg='#2c3e50')
        
        popup.update_idletasks()
        main_x = self.master.winfo_x()
        main_y = self.master.winfo_y()
        main_width = self.master.winfo_width()
        popup_x = main_x + main_width + 10
        popup_y = main_y
        popup.geometry(f"700x700+{popup_x}+{popup_y}")
        
        popup.transient(self.master)
        popup.grab_set()
        
        tk.Label(popup, text="🎯 Select Exercise", font=('Helvetica', 16, 'bold'), bg='#2c3e50', fg='#ecf0f1').pack(pady=12)

        # Left side: folder/exercise tree
        body = tk.Frame(popup, bg='#2c3e50')
        body.pack(fill='both', expand=True, padx=16, pady=8)

        left = tk.Frame(body, bg='#2c3e50')
        left.pack(side='left', fill='both', expand=True)
        right = tk.Frame(body, bg='#2c3e50')
        right.pack(side='right', fill='y')

        tree = ttk.Treeview(left, show='tree')
        tree.pack(side='left', fill='both', expand=True)
        scr = ttk.Scrollbar(left, orient='vertical', command=tree.yview)
        scr.pack(side='right', fill='y')
        tree.configure(yscrollcommand=scr.set)

        root_node = tree.insert('', 'end', text='All Exercises', open=True)
        for folder_name, items in sorted(self.exercises_structure.get('folders', {}).items()):
            fnode = tree.insert(root_node, 'end', text=f"📁 {folder_name}", open=False)
            for ex_name in sorted(items):
                tree.insert(fnode, 'end', text=self.decorate_stale_label(ex_name))
        for ex_name in sorted(self.exercises_structure.get('root', [])):
            tree.insert(root_node, 'end', text=self.decorate_stale_label(ex_name))

        # Right panel: brief statistics
        stats_title = tk.Label(right, text="Statistics", font=('Helvetica', 12, 'bold'), bg='#2c3e50', fg='#ecf0f1')
        stats_title.pack(pady=(0, 6))
        stats_text = tk.Label(right, text="—", font=('Helvetica', 10), bg='#2c3e50', fg='#ecf0f1', justify='left')
        stats_text.pack()

        selected_exercise = {'name': None}

        def update_stats_for(ex_name):
            if not ex_name:
                stats_text.config(text='—')
                return
            try:
                st = self.get_exercise_stats(ex_name)
                best = self.get_best_bpm(ex_name)
                last = self.get_last_played_date(ex_name) or '—'
                stats_display = f"• Sessions: {st['total_sessions']}\n• Total Time: {st['total_time_formatted']}\n• Best BPM: {best}\n• Last Played: {last}"
                stats_text.config(text=stats_display)
            except Exception as e:
                stats_text.config(text='—')

        def on_select(event):
            sel = tree.selection()
            if not sel:
                return
            node = sel[0]
            text = tree.item(node, 'text')
            # Folder nodes start with "📁 "; exercises do not
            if text.startswith('📁 '):
                selected_exercise['name'] = None
                update_stats_for(None)
            elif text == 'All Exercises':
                selected_exercise['name'] = None
                update_stats_for(None)
            else:
                # Remove "🔴" label if present
                clean_text = text.replace('🔴', '').strip()
                # Also remove extra spaces
                clean_text = ' '.join(clean_text.split())
                selected_exercise['name'] = clean_text
                update_stats_for(clean_text)

        tree.bind('<<TreeviewSelect>>', on_select)
        
        # Buttons
        button_frame = tk.Frame(popup, bg='#2c3e50')
        button_frame.pack(side='bottom', pady=16, fill='x', padx=16)
        
        def start_selected_exercise():
            chosen = selected_exercise['name']
            if chosen:
                self.current_exercise = chosen
                popup.destroy()
                self.start_timer()
            else:
                messagebox.showwarning("Warning", "Select Exercise!")
        
        def cancel_popup():
            popup.destroy()
            self.show_main_screen()
        
        tk.Button(button_frame, text="🎯 Start Exercise", font=('Helvetica', 12, 'bold'), bg='#3498db', fg='white', relief='flat', padx=20, pady=10, command=start_selected_exercise).pack(side='left', padx=10, expand=True)
        tk.Button(button_frame, text="🔙 Cancel", font=('Helvetica', 12, 'bold'), bg='#95a5a6', fg='white', relief='flat', padx=20, pady=10, command=cancel_popup).pack(side='right', padx=10, expand=True)


    def start_timer(self):
        """Start timer"""
        # Check if exercise is selected
        if hasattr(self, 'exercise_var') and not self.exercise_var.get():
            messagebox.showwarning("Warning", "Select Exercise!")
            return
            
        # If current_exercise is already set (from popup), use it
        if not self.current_exercise:
            self.current_exercise = self.exercise_var.get()
            
        # Hide main menu and other screens
        self.button_frame.pack_forget()
        self.exercise_frame.pack_forget()
        self.history_frame.pack_forget()
        self.exercises_manage_frame.pack_forget()
        self.timer_frame.pack(fill='both', expand=True, padx=20, pady=20)
        
        # Clear frame
        for widget in self.timer_frame.winfo_children():
            widget.destroy()
        
        # Exercise information
        tk.Label(self.timer_frame, 
                text=f"🎸 {self.current_exercise}", 
                font=('Helvetica', 20, 'bold'),
                bg='#34495e', fg='#ecf0f1').pack(pady=20)
        
        # Timer
        self.time_label = tk.Label(self.timer_frame, 
                                  text="00:00", 
                                  font=('Helvetica', 48, 'bold'),
                                  bg='#34495e', fg='#3498db')
        self.time_label.pack(pady=20)
        
        # Exercise info: best BPM, last played date, total time
        info_frame = tk.Frame(self.timer_frame, bg='#34495e')
        info_frame.pack(pady=(0, 10))
        try:
            best_bpm = self.get_best_bpm(self.current_exercise)
            last_played = self.get_last_played_date(self.current_exercise) or "—"
            total_time = self.get_exercise_stats(self.current_exercise)['total_time_formatted']
            self.exercise_info_label = tk.Label(info_frame,
                                                text=f"🏆 Best BPM: {best_bpm}   |   🗓️ Last Played: {last_played}   |   ⏱️ Total Time: {total_time}",
                                                font=('Helvetica', 10, 'bold'),
                                                bg='#34495e', fg='#bdc3c7')
        except Exception as e:
            self.exercise_info_label = tk.Label(info_frame,
                                                text=f"🏆 Best BPM: 0   |   🗓️ Last Played: —   |   ⏱️ Total Time: 00:00",
                                                font=('Helvetica', 10, 'bold'),
                                                bg='#34495e', fg='#bdc3c7')
        self.exercise_info_label.pack()

        # INFO button for current exercise (compact, in top right corner of timer)
        info_btn = tk.Button(self.timer_frame, text='ℹ️', font=('Helvetica', 9, 'bold'), bg='#2980b9', fg='white', relief='flat', padx=6, pady=2, command=self.show_current_exercise_info)
        info_btn.place(relx=0.98, rely=0.02, anchor='ne')
        
        # Metronome section
        metronome_frame = tk.Frame(self.timer_frame, bg='#34495e')
        metronome_frame.pack(pady=20)
        
        # Metronome title
        tk.Label(metronome_frame, 
                text="🎵 Metronome", 
                font=('Helvetica', 14, 'bold'),
                bg='#34495e', fg='#ecf0f1').pack()
        
        # BPM display and control
        bpm_frame = tk.Frame(metronome_frame, bg='#34495e')
        bpm_frame.pack(pady=10)
        
        self.bpm_label = tk.Label(bpm_frame, 
                                 text=f"BPM: {self.metronome_bpm}", 
                                 font=('Helvetica', 16, 'bold'),
                                 bg='#34495e', fg='#3498db')
        self.bpm_label.pack()
        
        # BPM and volume control buttons
        bpm_buttons_frame = tk.Frame(metronome_frame, bg='#34495e')
        bpm_buttons_frame.pack(pady=10)
        for text, delta in [("-5", -5), ("-1", -1)]:
            tk.Button(bpm_buttons_frame, text=text, font=('Helvetica', 10, 'bold'), bg='#e74c3c', fg='white',
                     relief='flat', padx=10, pady=5, command=lambda d=delta: self.change_bpm(d)).pack(side='left', padx=2)
        self.metronome_start_btn = tk.Button(bpm_buttons_frame, text="▶️ Start", font=('Helvetica', 10, 'bold'),
                                            bg='#27ae60', fg='white', relief='flat', padx=15, pady=5,
                                            command=self.toggle_metronome)
        self.metronome_start_btn.pack(side='left', padx=5)
        for text, delta in [("+1", 1), ("+5", 5)]:
            tk.Button(bpm_buttons_frame, text=text, font=('Helvetica', 10, 'bold'), bg='#e74c3c', fg='white',
                     relief='flat', padx=10, pady=5, command=lambda d=delta: self.change_bpm(d)).pack(side='left', padx=2)

        # Volume button (dropdown control)
        volume_button = tk.Menubutton(bpm_buttons_frame, text="🔊", font=('Helvetica', 10, 'bold'), bg='#34495e', fg='#ecf0f1', relief='flat')
        volume_menu = tk.Menu(volume_button, tearoff=0, bg='#2c3e50', fg='#ecf0f1')
        volume_button.config(menu=volume_menu)
        volume_menu.add_command(label="Quieter", command=lambda: self.change_volume(-0.1))
        volume_menu.add_command(label="Louder", command=lambda: self.change_volume(0.1))
        volume_menu.add_separator()
        volume_menu.add_command(label="50%", command=lambda: self.set_volume(0.5))
        volume_menu.add_command(label="75%", command=lambda: self.set_volume(0.75))
        volume_menu.add_command(label="100%", command=lambda: self.set_volume(1.0))
        volume_button.pack(side='left', padx=6)
        
        # Exercise control buttons
        control_frame = tk.Frame(self.timer_frame, bg='#34495e')
        control_frame.pack(pady=20)
        buttons = [("⏸️ Pause", '#f39c12', self.pause_timer, True), ("✅ Finish", '#27ae60', self.finish_exercise, False),
                  ("🔙 Cancel", '#e74c3c', self.cancel_exercise, False)]
        for text, bg, cmd, is_pause in buttons:
            btn = tk.Button(control_frame, text=text, font=('Helvetica', 12, 'bold'), bg=bg, fg='white',
                           relief='flat', padx=20, pady=10, command=cmd)
            btn.pack(side='left', padx=10)
            if is_pause:
                self.pause_btn = btn
        
        # Start timer
        self.timer_running = True
        self.elapsed_time = 0
        self.update_timer()

    def update_timer(self):
        """Update timer"""
        if self.timer_running:
            self.time_label.config(text=self._format_time(self.elapsed_time))
            self.elapsed_time += 1
            self.master.after(1000, self.update_timer)

    def pause_timer(self):
        """Pause/resume timer"""
        if self.timer_running:
            # Pause
            self.timer_running = False
            self.pause_btn.config(text="▶️ Resume")
            # Remember metronome state and stop it
            self.metronome_was_running_before_pause = self.metronome_running
            if self.metronome_running:
                self._stop_metronome()
        else:
            # Resume
            self.timer_running = True
            self.pause_btn.config(text="⏸️ Pause")
            self.update_timer()
            # Resume metronome if it was running before pause
            if self.metronome_was_running_before_pause and not self.metronome_running:
                self.metronome_running = True
                if hasattr(self, 'metronome_start_btn'):
                    try:
                        self.metronome_start_btn.winfo_exists()
                        self.metronome_start_btn.config(text="⏸️ Stop", bg='#e74c3c')
                    except (tk.TclError, AttributeError):
                        pass
                self.metronome_thread = threading.Thread(target=self.metronome_loop, daemon=True)
                self.metronome_thread.start()
                self.metronome_was_running_before_pause = False

    def finish_exercise(self):
        """Finish exercise"""
        self.timer_running = False
        self.show_exercise_data_input()

    def cancel_exercise(self):
        """Cancel exercise"""
        self.timer_running = False
        self._stop_metronome()
        self.show_main_screen()

    def show_exercise_data_input(self):
        """Show exercise data input"""
        for widget in self.timer_frame.winfo_children():
            widget.destroy()
        tk.Label(self.timer_frame, text="📊 Exercise Data", font=('Helvetica', 18, 'bold'),
                bg='#34495e', fg='#ecf0f1').pack(pady=20)
        tk.Label(self.timer_frame, text=f"Execution Time: {self._format_time(self.elapsed_time - 1)}",
                font=('Helvetica', 14), bg='#34495e', fg='#bdc3c7').pack(pady=10)
        input_frame = tk.Frame(self.timer_frame, bg='#34495e')
        input_frame.pack(pady=20)
        tk.Label(input_frame, text="Best BPM:", font=('Helvetica', 12), bg='#34495e', fg='#ecf0f1').pack(anchor='w')
        self.bpm_entry = tk.Entry(input_frame, font=('Helvetica', 12), width=20)
        best_bpm = self.get_best_bpm(self.current_exercise) if self.current_exercise else 0
        default_bpm = best_bpm if best_bpm > 0 else self.metronome_bpm
        self.bpm_entry.insert(0, str(default_bpm))
        self.bpm_entry.pack(pady=5)
        button_frame = tk.Frame(self.timer_frame, bg='#34495e')
        button_frame.pack(pady=30)
        tk.Button(button_frame, text="🏁 Finish", font=('Helvetica', 12, 'bold'), bg='#27ae60', fg='white',
                 relief='flat', padx=20, pady=10, command=self.finish_workout).pack(side='left', padx=10)
        tk.Button(button_frame, text="🔄 Continue Workout", font=('Helvetica', 12, 'bold'), bg='#3498db', fg='white',
                 relief='flat', padx=20, pady=10, command=self.save_and_continue).pack(side='left', padx=10)

    def save_exercise(self):
        """Save exercise"""
        if not self._save_workout_data(self.bpm_entry.get()):
            return
        messagebox.showinfo("Success", "Exercise saved!")
        self.show_main_screen()

    def finish_workout(self):
        """Finish workout and return to main menu"""
        if not self._save_workout_data(self.bpm_entry.get()):
            return
        messagebox.showinfo("Workout Completed", "Data saved! Returning to main menu.")
        self.show_main_screen()

    def save_and_continue(self):
        """Save and continue"""
        if not self._save_workout_data(self.bpm_entry.get()):
            return
        self.elapsed_time = 0
        self.show_exercise_popup()

    def manage_exercises(self):
        """Manage Exercises"""
        # Destroy any remaining ghost windows before recreating interface
        if hasattr(self, '_drag_ghost') and self._drag_ghost is not None:
            try:
                self._drag_ghost.destroy()
            except Exception:
                pass
            self._drag_ghost = None
        
        self.button_frame.pack_forget()
        self.exercises_manage_frame.pack(fill='both', expand=True, padx=20, pady=20)
        
        # Clear frame
        for widget in self.exercises_manage_frame.winfo_children():
            widget.destroy()
        
        # Header and back button at top
        header_frame = tk.Frame(self.exercises_manage_frame, bg='#34495e')
        header_frame.pack(fill='x', pady=20, padx=20)
        
        tk.Label(header_frame, 
                text="📝 Manage Exercises", 
                font=('Helvetica', 18, 'bold'),
                bg='#34495e', fg='#ecf0f1').pack(side='left')
        
        tk.Button(header_frame, 
                 text="🔙 Back", 
                 font=('Helvetica', 10, 'bold'),
                 bg='#95a5a6', fg='white',
                 relief='flat', padx=15, pady=5,
                 command=self.show_main_screen).pack(side='right')
        
        # Top panel: create folder and add exercise via dialog
        add_frame = tk.Frame(self.exercises_manage_frame, bg='#34495e')
        add_frame.pack(pady=10, fill='x', padx=20)
        # Folder
        tk.Label(add_frame, text="New Folder:", font=('Helvetica', 10), bg='#34495e', fg='#ecf0f1').pack(side='left')
        self.new_folder_entry = tk.Entry(add_frame, font=('Helvetica', 10), width=20)
        self.new_folder_entry.pack(side='left', padx=6)
        tk.Button(add_frame, text="📁 Create", font=('Helvetica', 10, 'bold'), bg='#27ae60', fg='white', relief='flat', padx=10, pady=4, command=self.create_folder).pack(side='left', padx=6)
        # Exercise addition dialog
        tk.Button(add_frame, text="🗂️ Add Exercise", font=('Helvetica', 10, 'bold'), bg='#27ae60', fg='white', relief='flat', padx=12, pady=4, command=self.open_add_exercise_dialog).pack(side='left', padx=(20, 0))
        tk.Button(add_frame, text="🗑️ Delete Folder", font=('Helvetica', 10, 'bold'), bg='#e74c3c', fg='white', relief='flat', padx=12, pady=4, command=self.delete_folder_dialog).pack(side='left', padx=6)

        # INFO for selected exercise
        info_frame = tk.Frame(self.exercises_manage_frame, bg='#34495e')
        info_frame.pack(fill='x', padx=20, pady=(6, 6))
        tk.Label(info_frame, text="INFO: link/note", font=('Helvetica', 10, 'bold'), bg='#34495e', fg='#ecf0f1').pack(anchor='w')
        info_inputs = tk.Frame(info_frame, bg='#34495e')
        info_inputs.pack(fill='x')
        # Use grid layout so Save button always fits
        tk.Label(info_inputs, text="Link:", font=('Helvetica', 9), bg='#34495e', fg='#ecf0f1').grid(row=0, column=0, sticky='w')
        self.info_link_var = tk.StringVar()
        self.info_entry = tk.Entry(info_inputs, textvariable=self.info_link_var, font=('Helvetica', 10), width=45)
        self.info_entry.grid(row=0, column=1, sticky='we', padx=6, pady=2)
        tk.Label(info_inputs, text="Note:", font=('Helvetica', 9), bg='#34495e', fg='#ecf0f1').grid(row=0, column=2, sticky='w', padx=(10,0))
        self.info_note_var = tk.StringVar()
        self.info_note_entry = tk.Entry(info_inputs, textvariable=self.info_note_var, font=('Helvetica', 10), width=28)
        self.info_note_entry.grid(row=0, column=3, sticky='we', padx=6, pady=2)
        btns = tk.Frame(info_inputs, bg='#34495e')
        btns.grid(row=1, column=0, columnspan=4, sticky='w', pady=4)
        tk.Button(btns, text="💾 Save", font=('Helvetica', 9), bg='#2980b9', fg='white', relief='flat', padx=8, pady=3, command=self.save_selected_info).pack(side='left')
        info_inputs.columnconfigure(1, weight=1)
        info_inputs.columnconfigure(3, weight=1)

        # Folder/exercise tree
        tree_frame = tk.Frame(self.exercises_manage_frame, bg='#34495e')
        tree_frame.pack(fill='both', expand=True, padx=20, pady=10)
        self.ex_tree = ttk.Treeview(tree_frame, show='tree')
        self.ex_tree.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.ex_tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.ex_tree.configure(yscrollcommand=scrollbar.set)

        root_node = self.ex_tree.insert('', 'end', text='All Exercises', open=True)
        # Folders (closed by default)
        for folder_name, items in sorted(self.exercises_structure.get('folders', {}).items()):
            fnode = self.ex_tree.insert(root_node, 'end', text=f"📁 {folder_name}", open=False)
            for ex_name in sorted(items):
                self.ex_tree.insert(fnode, 'end', text=ex_name)
        # Root exercises
        for ex_name in sorted(self.exercises_structure.get('root', [])):
            self.ex_tree.insert(root_node, 'end', text=ex_name)

        # Update INFO on selection
        def on_tree_select(event):
            sel = self.get_selected_tree_item()
            if not sel:
                self.info_link_var.set("")
                self.info_note_var.set("")
                return
            _, text = sel
            if text.startswith('📁 ') or text == 'All Exercises':
                self.info_link_var.set("")
                self.info_note_var.set("")
                return
            info = self.exercises_structure.get('info', {}).get(text, {})
            self.info_link_var.set(info.get('link', ''))
            self.info_note_var.set(info.get('note', ''))
        self.ex_tree.bind('<<TreeviewSelect>>', on_tree_select)

        # Drag & Drop movement of exercises between folders/root (with delay/threshold)
        self._drag_item_id = None
        self._drag_start_time = None
        self._drag_start_xy = None
        self._drag_ghost = None
        def _create_drag_ghost(text, x, y):
            try:
                ghost = tk.Toplevel(self.master)
                ghost.overrideredirect(True)
                try:
                    ghost.attributes('-alpha', 0.85)
                except Exception:
                    pass
                lbl = tk.Label(ghost, text=text, font=('Helvetica', 9, 'bold'), bg='#2c3e50', fg='#ecf0f1', padx=6, pady=2, relief='solid', bd=1)
                lbl.pack()
                ghost.lift()
                ghost.attributes('-topmost', True)
                ghost.geometry(f"+{x+12}+{y+12}")
                return ghost
            except Exception:
                return None
        def _move_drag_ghost(x, y):
            if self._drag_ghost is not None:
                try:
                    self._drag_ghost.geometry(f"+{x+12}+{y+12}")
                except Exception:
                    pass
        def _destroy_drag_ghost():
            if self._drag_ghost is not None:
                try:
                    self._drag_ghost.destroy()
                except Exception:
                    pass
                self._drag_ghost = None
        def on_drag_start(event):
            item = self.ex_tree.identify_row(event.y)
            if item:
                item_text = self.ex_tree.item(item, 'text')
                # Prevent dragging folders and root element
                if item_text not in ('All Exercises', ) and not item_text.startswith('📁 '):
                    self._drag_item_id = item
                    self._drag_start_time = time.time()
                    self._drag_start_xy = (event.x_root, event.y_root)
                    # Change cursor for grab feeling
                    try:
                        self.ex_tree.configure(cursor='fleur')
                    except Exception:
                        pass
        def on_drag_motion(event):
            if not self._drag_item_id:
                return
            dt = (time.time() - self._drag_start_time) if self._drag_start_time else 0
            dx = abs((event.x_root or 0) - (self._drag_start_xy[0] if self._drag_start_xy else 0))
            dy = abs((event.y_root or 0) - (self._drag_start_xy[1] if self._drag_start_xy else 0))
            if (dt >= 0.1 or (dx + dy) >= 4) and self._drag_ghost is None:
                dragged_text = self.ex_tree.item(self._drag_item_id, 'text')
                self._drag_ghost = _create_drag_ghost(dragged_text, event.x_root, event.y_root)
            _move_drag_ghost(event.x_root, event.y_root)
        def on_drag_release(event):
            if not self._drag_item_id:
                return
            # Time and offset threshold - if pressed and released quickly/without movement, consider it a click
            dt = (time.time() - self._drag_start_time) if self._drag_start_time else 0
            dx = abs((event.x_root or 0) - (self._drag_start_xy[0] if self._drag_start_xy else 0))
            dy = abs((event.y_root or 0) - (self._drag_start_xy[1] if self._drag_start_xy else 0))
            if dt < 0.2 and (dx + dy) < 8:
                self._cleanup_drag()
                return
            target = self.ex_tree.identify_row(event.y)
            dragged_text = self.ex_tree.item(self._drag_item_id, 'text')
            if not target or dragged_text.startswith('📁 '):
                self._cleanup_drag()
                return
            target_text = self.ex_tree.item(target, 'text')
            if target_text and not target_text.startswith('📁 ') and target_text != 'All Exercises':
                target = self.ex_tree.parent(target)
                target_text = self.ex_tree.item(target, 'text')
            
            # Remove from all locations
            root_list = self.exercises_structure.get('root', [])
            if dragged_text in root_list:
                root_list.remove(dragged_text)
            for items in self.exercises_structure.get('folders', {}).values():
                if dragged_text in items:
                    items.remove(dragged_text)
            
            # Add to destination
            if target_text == 'All Exercises':
                root_list = self.exercises_structure.setdefault('root', [])
                if dragged_text not in root_list:
                    root_list.append(dragged_text)
            elif target_text.startswith('📁 '):
                folder_list = self.exercises_structure.setdefault('folders', {}).setdefault(target_text[2:].strip(), [])
                if dragged_text not in folder_list:
                    folder_list.append(dragged_text)
            try:
                self.save_exercise_structure()
                self.exercises = self.flatten_exercises()
                self._cleanup_drag()
                self.manage_exercises()
            except Exception:
                self._cleanup_drag()
                raise
        self.ex_tree.bind('<ButtonPress-1>', on_drag_start)
        self.ex_tree.bind('<B1-Motion>', on_drag_motion)
        self.ex_tree.bind('<ButtonRelease-1>', on_drag_release)
        
        def cleanup_on_release_outside(event):
            widget = event.widget
            if widget != self.ex_tree and not str(widget).startswith(str(self.ex_tree)):
                if hasattr(self, '_drag_item_id') and self._drag_item_id:
                    self._cleanup_drag()
        
        # Bind handler to frame for cleaning ghost windows
        self.exercises_manage_frame.bind('<ButtonRelease-1>', cleanup_on_release_outside)

        # Movement control panel
        move_frame = tk.Frame(self.exercises_manage_frame, bg='#34495e')
        move_frame.pack(fill='x', padx=20, pady=(0, 10))
        tk.Button(move_frame, text="➡️ To Folder", font=('Helvetica', 9), bg='#f39c12', fg='white', relief='flat', padx=10, pady=4, command=self.move_selected_to_folder).pack(side='left', padx=5)
        tk.Button(move_frame, text="🗑️ Remove from Folder", font=('Helvetica', 9), bg='#e74c3c', fg='white', relief='flat', padx=10, pady=4, command=self.remove_selected_from_folder).pack(side='left', padx=5)
        tk.Button(move_frame, text="📈 Chart", font=('Helvetica', 9), bg='#9b59b6', fg='white', relief='flat', padx=10, pady=4, command=self.show_stats_for_selected).pack(side='left', padx=5)
        tk.Button(move_frame, text="🗑️ Delete exercise", font=('Helvetica', 9), bg='#e74c3c', fg='white', relief='flat', padx=10, pady=4, command=self.delete_selected_exercise).pack(side='left', padx=5)
        tk.Button(move_frame, text="✏️ Rename", font=('Helvetica', 9), bg='#8e44ad', fg='white', relief='flat', padx=10, pady=4, command=self.rename_selected_exercise).pack(side='left', padx=5)
        
        # Back button - place in separate frame at bottom
        back_frame = tk.Frame(self.exercises_manage_frame, bg='#34495e')
        back_frame.pack(side='bottom', fill='x', pady=20)
        
        tk.Button(back_frame, 
                 text="🔙 Back", 
                font=('Helvetica', 12, 'bold'),
                 bg='#95a5a6', fg='white',
                 relief='flat', padx=20, pady=10,
                 command=self.show_main_screen).pack()


    def delete_exercise(self, exercise):
        """Delete exercise"""
        if messagebox.askyesno("Confirmation", f"Delete exercise '{exercise}'?"):
            if exercise in self.exercises_structure.get('root', []):
                self.exercises_structure['root'].remove(exercise)
            for items in self.exercises_structure.get('folders', {}).values():
                if exercise in items:
                    items.remove(exercise)
            self.exercises_structure.get('info', {}).pop(exercise, None)
            self.save_exercise_structure()
            self.exercises = self.flatten_exercises()
            self.manage_exercises()

    # Folder and INFO operations
    def create_folder(self):
        folder_name = self.new_folder_entry.get().strip()
        if not folder_name:
            return
        folders = self.exercises_structure.setdefault('folders', {})
        if folder_name not in folders:
            folders[folder_name] = []
            self.save_exercise_structure()
            self.manage_exercises()

    def get_selected_tree_item(self):
        sel = self.ex_tree.selection()
        if not sel:
            return None
        item_id = sel[0]
        text = self.ex_tree.item(item_id, 'text')
        return item_id, text

    def move_selected_to_folder(self):
        selected = self.get_selected_tree_item()
        if not selected:
            return
        item_id, text = selected
        # If exercise selected, ask for folder
        folder_choices = sorted(self.exercises_structure.get('folders', {}).keys())
        if not folder_choices:
            messagebox.showinfo("Info", "Please create a folder first")
            return
        # Simple selection window
        top = tk.Toplevel(self.master)
        top.title("Select Folder")
        top.configure(bg='#2c3e50')
        var = tk.StringVar(value=folder_choices[0])
        for name in folder_choices:
            tk.Radiobutton(top, text=name, variable=var, value=name, bg='#2c3e50', fg='#ecf0f1', selectcolor='#34495e').pack(anchor='w', padx=10, pady=2)
        def confirm():
            folder = var.get()
            if text in self.exercises_structure.get('root', []):
                self.exercises_structure['root'].remove(text)
            for items in self.exercises_structure.get('folders', {}).values():
                if text in items:
                    items.remove(text)
            folder_list = self.exercises_structure.setdefault('folders', {}).setdefault(folder, [])
            if text not in folder_list:
                folder_list.append(text)
            self.save_exercise_structure()
            self.exercises = self.flatten_exercises()
            top.destroy()
            self.manage_exercises()
        tk.Button(top, text='OK', command=confirm, bg='#27ae60', fg='white').pack(pady=8)


    def remove_selected_from_folder(self):
        selected = self.get_selected_tree_item()
        if not selected:
            return
        _, text = selected
        for items in self.exercises_structure.get('folders', {}).values():
            if text in items:
                items.remove(text)
        self.save_exercise_structure()
        self.exercises = self.flatten_exercises()
        self.manage_exercises()

    def show_stats_for_selected(self):
        selected = self.get_selected_tree_item()
        if not selected:
            return
        _, text = selected
        self.show_exercise_stats(text)

    def delete_selected_exercise(self):
        selected = self.get_selected_tree_item()
        if not selected:
            return
        _, text = selected
        self.delete_exercise(text)

    def rename_selected_exercise(self):
        selected = self.get_selected_tree_item()
        if not selected:
            return
        _, old_name = selected
        if old_name.startswith('📁 ') or old_name == 'All Exercises':
            return
        dlg = tk.Toplevel(self.master)
        dlg.title('Rename Exercise')
        dlg.configure(bg='#2c3e50')
        tk.Label(dlg, text='New Name:', bg='#2c3e50', fg='#ecf0f1').pack(padx=16, pady=(16,6), anchor='w')
        var = tk.StringVar(value=old_name)
        entry = tk.Entry(dlg, textvariable=var, width=40)
        entry.pack(padx=16, pady=6)
        def do_rename():
            new_name = var.get().strip()
            if not new_name or new_name == old_name:
                dlg.destroy()
                return
            # Update in root
            root_list = self.exercises_structure.get('root', [])
            for i, n in enumerate(root_list):
                if n == old_name:
                    root_list[i] = new_name
                    break
            # Update in folders
            for f, items in self.exercises_structure.get('folders', {}).items():
                for i, n in enumerate(items):
                    if n == old_name:
                        items[i] = new_name
                        break
            # Update INFO
            info = self.exercises_structure.get('info', {})
            if old_name in info:
                info[new_name] = info.pop(old_name)
            self.save_exercise_structure()
            self.exercises = self.flatten_exercises()
            dlg.destroy()
            self.manage_exercises()
        btns = tk.Frame(dlg, bg='#2c3e50')
        btns.pack(pady=8)
        tk.Button(btns, text='Save', bg='#27ae60', fg='white', relief='flat', padx=12, command=do_rename).pack(side='left', padx=6)
        tk.Button(btns, text='Cancel', bg='#95a5a6', fg='white', relief='flat', padx=12, command=dlg.destroy).pack(side='left')

    def open_add_exercise_dialog(self):
        """Open exercise addition dialog with folder selection, note and link"""
        dlg = tk.Toplevel(self.master)
        dlg.title("Add Exercise")
        dlg.configure(bg='#2c3e50')
        dlg.geometry('520x260')
        dlg.transient(self.master)
        dlg.grab_set()

        cont = tk.Frame(dlg, bg='#2c3e50')
        cont.pack(fill='both', expand=True, padx=16, pady=16)

        # Name
        tk.Label(cont, text='Name:', bg='#2c3e50', fg='#ecf0f1').grid(row=0, column=0, sticky='w')
        name_var = tk.StringVar()
        name_entry = tk.Entry(cont, textvariable=name_var, width=40)
        name_entry.grid(row=0, column=1, columnspan=3, sticky='we', pady=4)

        # Folder
        tk.Label(cont, text='Folder:', bg='#2c3e50', fg='#ecf0f1').grid(row=1, column=0, sticky='w')
        folders = ['Root'] + sorted(self.exercises_structure.get('folders', {}).keys())
        folder_var = tk.StringVar(value='Root')
        folder_cb = ttk.Combobox(cont, textvariable=folder_var, values=folders, state='readonly', width=20)
        folder_cb.grid(row=1, column=1, sticky='w', pady=4)

        # Note and link
        tk.Label(cont, text='Link:', bg='#2c3e50', fg='#ecf0f1').grid(row=2, column=0, sticky='w')
        link_var = tk.StringVar()
        tk.Entry(cont, textvariable=link_var, width=40).grid(row=2, column=1, columnspan=3, sticky='we', pady=4)

        tk.Label(cont, text='Note:', bg='#2c3e50', fg='#ecf0f1').grid(row=3, column=0, sticky='w')
        note_var = tk.StringVar()
        tk.Entry(cont, textvariable=note_var, width=40).grid(row=3, column=1, columnspan=3, sticky='we', pady=4)

        # Buttons
        btns = tk.Frame(cont, bg='#2c3e50')
        btns.grid(row=4, column=0, columnspan=4, pady=10, sticky='e')
        def add_now():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning('Warning', 'Enter exercise name!')
                return
            if name in self.flatten_exercises():
                messagebox.showwarning('Warning', 'Such exercise already exists!')
                return
            folder = folder_var.get()
            if folder == 'Root':
                self.exercises_structure.setdefault('root', []).append(name)
            else:
                self.exercises_structure.setdefault('folders', {}).setdefault(folder, []).append(name)
            self.exercises_structure.setdefault('info', {})[name] = {
                'link': link_var.get().strip(), 'note': note_var.get().strip()
            }
            self.save_exercise_structure()
            self.exercises = self.flatten_exercises()
            dlg.destroy()
            self.manage_exercises()
        tk.Button(btns, text='Add', bg='#27ae60', fg='white', relief='flat', padx=12, command=add_now).pack(side='right', padx=6)
        tk.Button(btns, text='Cancel', bg='#95a5a6', fg='white', relief='flat', padx=12, command=dlg.destroy).pack(side='right')

    def delete_folder_dialog(self):
        folders = sorted(self.exercises_structure.get('folders', {}).keys())
        if not folders:
            messagebox.showinfo('Info', 'No folders to delete')
            return
        dlg = tk.Toplevel(self.master)
        dlg.title('Delete Folder')
        dlg.configure(bg='#2c3e50')
        tk.Label(dlg, text='Select Folder to delete:', bg='#2c3e50', fg='#ecf0f1').pack(padx=16, pady=(16,6), anchor='w')
        var = tk.StringVar(value=folders[0])
        for name in folders:
            tk.Radiobutton(dlg, text=name, variable=var, value=name, bg='#2c3e50', fg='#ecf0f1', selectcolor='#34495e').pack(anchor='w', padx=16)
        def do_delete():
            items = self.exercises_structure.get('folders', {}).pop(var.get(), [])
            root_list = self.exercises_structure.setdefault('root', [])
            root_list.extend(ex for ex in items if ex not in root_list)
            self.save_exercise_structure()
            dlg.destroy()
            self.manage_exercises()
        btns = tk.Frame(dlg, bg='#2c3e50')
        btns.pack(pady=12)
        tk.Button(btns, text='Delete', bg='#e74c3c', fg='white', relief='flat', padx=12, command=do_delete).pack(side='left', padx=6)
        tk.Button(btns, text='Cancel', bg='#95a5a6', fg='white', relief='flat', padx=12, command=dlg.destroy).pack(side='left')

    def save_selected_info(self):
        selected = self.get_selected_tree_item()
        if not selected:
            return
        _, text = selected
        info_map = self.exercises_structure.setdefault('info', {})
        info_map[text] = {
            'link': self.info_link_var.get().strip(),
            'note': self.info_note_var.get().strip()
        }
        self.save_exercise_structure()

    def get_exercise_stats(self, exercise_name):
        """Get statistics for exercise"""
        # Filter data by exercise (exact match)
        exercise_data = [data for data in self.workout_data if data.get('exercise') == exercise_name]
        
        if not exercise_data:
            return {
                'total_sessions': 0,
                'total_time_seconds': 0,
                'total_time_formatted': '00:00',
                'avg_bpm': 0
            }
        
        # Calculate total time in seconds
        total_seconds = 0
        total_bpm = 0
        valid_bpm_count = 0
        
        for data in exercise_data:
            total_seconds += self._parse_time(data.get('time', '00:00'))
            
            # Calculate average BPM
            try:
                if data['bpm'].isdigit():
                    total_bpm += int(data['bpm'])
                    valid_bpm_count += 1
            except (ValueError, KeyError):
                continue
        
        total_time_formatted = self._format_time(total_seconds)
        
        # Calculate average BPM
        avg_bpm = total_bpm // valid_bpm_count if valid_bpm_count > 0 else 0
        
        return {
            'total_sessions': len(exercise_data),
            'total_time_seconds': total_seconds,
            'total_time_formatted': total_time_formatted,
            'avg_bpm': avg_bpm
        }

    def get_best_bpm(self, exercise_name):
        """Find best BPM for exercise"""
        best = 0
        for data in self.workout_data:
            if data.get('exercise') == exercise_name and str(data.get('bpm', '')).isdigit():
                best = max(best, int(data['bpm']))
        return best

    def _get_last_played_timestamp(self, exercise_name):
        """Get last played timestamp for exercise"""
        last_ts = None
        for data in self.workout_data:
            if data.get('exercise') == exercise_name:
                try:
                    ts = datetime.fromisoformat(data['timestamp'])
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
                except Exception:
                    continue
        return last_ts

    def get_last_played_date(self, exercise_name):
        """Get last played date for exercise in DD Month YYYY format"""
        last_ts = self._get_last_played_timestamp(exercise_name)
        return last_ts.strftime('%d %B %Y') if last_ts else None

    def is_stale_exercise(self, exercise_name):
        """Return True if exercise hasn't been played for >= self.stale_days"""
        last_ts = self._get_last_played_timestamp(exercise_name)
        if last_ts is None:
            return self.stale_days > 0
        return (datetime.now() - last_ts).days >= self.stale_days

    def decorate_stale_label(self, exercise_name):
        if self.is_stale_exercise(exercise_name):
            return f"{exercise_name}    🔴"
        return exercise_name

    def open_settings(self):
        win = tk.Toplevel(self.master)
        win.title('Settings')
        win.configure(bg='#2c3e50')
        win.geometry('360x250')
        tk.Label(win, text='After how many days consider exercise as "not played recently"', bg='#2c3e50', fg='#ecf0f1', wraplength=320).pack(pady=12)
        val = tk.IntVar(value=int(self.stale_days))
        tk.Spinbox(win, from_=1, to=60, textvariable=val, width=5).pack()
        def save_and_close():
            self.stale_days = int(val.get())
            self.save_settings()
            win.destroy()
        tk.Button(win, text='Save', bg='#27ae60', fg='white', relief='flat', padx=12, command=save_and_close).pack(pady=12)
        tk.Button(win, text='Close', bg='#95a5a6', fg='white', relief='flat', padx=12, command=win.destroy).pack(pady=5)
        
        # GitHub link
        github_frame = tk.Frame(win, bg='#2c3e50')
        github_frame.pack(pady=15)
        tk.Label(github_frame, text='Project on GitHub:', bg='#2c3e50', fg='#ecf0f1', font=('Helvetica', 9)).pack()
        github_link = tk.Label(github_frame, text='https://github.com/Leesty/Guitar-Trainer-/tree/main', 
                              bg='#2c3e50', fg='#3498db', cursor='hand2', font=('Helvetica', 9, 'underline'))
        github_link.pack(pady=5)
        github_link.bind('<Button-1>', lambda e: webbrowser.open('https://github.com/Leesty/Guitar-Trainer-/tree/main'))

    def show_current_exercise_info(self):
        """Show INFO window for current exercise: link, note"""
        ex = self.current_exercise
        info = self.exercises_structure.get('info', {}).get(ex, {})
        link, note = info.get('link'), info.get('note')
        win = tk.Toplevel(self.master)
        win.title(f"INFO: {ex}")
        win.configure(bg='#2c3e50')
        win.geometry('600x400')
        tk.Label(win, text=ex, font=('Helvetica', 14, 'bold'), bg='#2c3e50', fg='#ecf0f1').pack(pady=8)
        for label, value in [('Link', link), ('Note', note)]:
            frame = tk.Frame(win, bg='#2c3e50')
            frame.pack(fill='x', padx=12, pady=6)
            tk.Label(frame, text=f'{label}:', bg='#2c3e50', fg='#ecf0f1').pack(side='left')
            lbl = tk.Label(frame, text=value or '—', bg='#2c3e50', fg='#3498db' if label == 'Link' else '#ecf0f1',
                          cursor='hand2' if label == 'Link' else '', wraplength=520 if label == 'Note' else 0,
                          justify='left' if label == 'Note' else 'center')
            lbl.pack(side='left', padx=6)
            if label == 'Link' and link:
                lbl.bind('<Button-1>', lambda e, l=link: webbrowser.open(l))
        tk.Button(win, text='Close', bg='#95a5a6', fg='white', relief='flat', padx=12, command=win.destroy).pack(pady=20)

    def get_total_training_time(self):
        """Get total time of all workouts"""
        total_seconds = sum(self._parse_time(data.get('time', '00:00')) for data in self.workout_data)
        return f"⏱️ Total Time: {self._format_time(total_seconds)}"

    def update_total_time_display(self):
        """Update total time display"""
        if hasattr(self, 'total_time_label'):
            self.total_time_label.config(text=self.get_total_training_time())

    def change_bpm(self, delta):
        """Change BPM by specified value"""
        new_bpm = self.metronome_bpm + delta
        if 30 <= new_bpm <= 200:  # Minimum value set to 30
            self.metronome_bpm = new_bpm
            if hasattr(self, 'bpm_label'):
                self.bpm_label.config(text=f"BPM: {self.metronome_bpm}")

    def set_volume(self, volume):
        """Set metronome volume (0.0 - 1.0)"""
        self.metronome_volume = max(0.0, min(1.0, volume))

    def change_volume(self, delta):
        """Change metronome volume by delta"""
        self.set_volume(self.metronome_volume + delta)

    def toggle_metronome(self):
        """Toggle metronome on/off"""
        if not self.metronome_running:
            self.metronome_running = True
            try:
                if hasattr(self, 'metronome_start_btn'):
                    self.metronome_start_btn.winfo_exists()
                    self.metronome_start_btn.config(text="⏸️ Stop", bg='#e74c3c')
            except (tk.TclError, AttributeError):
                pass
            self.metronome_thread = threading.Thread(target=self.metronome_loop, daemon=True)
            self.metronome_thread.start()
        else:
            self.metronome_running = False
            try:
                if hasattr(self, 'metronome_start_btn'):
                    self.metronome_start_btn.winfo_exists()
                    self.metronome_start_btn.config(text="▶️ Start", bg='#27ae60')
            except (tk.TclError, AttributeError):
                pass

    def metronome_loop(self):
        """Metronome loop"""
        try:
            # Load metronome sound
            metronome_file = os.path.join(self.script_dir, 'untitled.wav')
            if os.path.exists(metronome_file):
                metronome_sound = pygame.mixer.Sound(metronome_file)
            else:
                # Fallback to winsound if file not found
                metronome_sound = None
        except:
            metronome_sound = None
            
        while self.metronome_running:
            try:
                if metronome_sound:
                    metronome_sound.set_volume(self.metronome_volume)
                    metronome_sound.play()
                else:
                    # Fallback to winsound
                    duration_ms = int(50)
                    try:
                        winsound.Beep(400, duration_ms)
                    except RuntimeError:
                        pass
                time.sleep(60.0 / self.metronome_bpm)
            except:
                break

    def view_history(self):
        """View workout history"""
        self.button_frame.pack_forget()
        self.history_frame.pack(fill='both', expand=True, padx=20, pady=20)
        
        # Clear frame
        for widget in self.history_frame.winfo_children():
            widget.destroy()
        
        # Title
        tk.Label(self.history_frame, 
                text="📊 Workout History", 
                font=('Helvetica', 18, 'bold'),
                bg='#34495e', fg='#ecf0f1').pack(pady=20)
        
        if not self.workout_data:
            tk.Label(self.history_frame, 
                    text="Workout history is empty", 
                    font=('Helvetica', 14),
                    bg='#34495e', fg='#bdc3c7').pack(pady=50)
        else:
            days_data = self._group_data_by_days()
            
            # Create scrollable frame for days
            canvas = tk.Canvas(self.history_frame, bg='#34495e', highlightthickness=0, height=400)
            scrollbar = ttk.Scrollbar(self.history_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = tk.Frame(canvas, bg='#34495e')
            
            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            
            # Display days
            for date in self._sort_dates(days_data.keys()):
                day_frame = tk.Frame(scrollable_frame, bg='#34495e', relief='raised', bd=1)
                day_frame.pack(fill='x', pady=5, padx=10)
                
                # Day header with delete button
                day_header_frame = tk.Frame(day_frame, bg='#34495e')
                day_header_frame.pack(fill='x', padx=10, pady=5)
                
                total_day_seconds = sum(self._parse_time(data.get('time', '00:00')) for data in days_data[date])
                total_day_time = self._format_time(total_day_seconds)
                
                tk.Label(day_header_frame, 
                        text=f"📅 {date} | ⏱️ Total Time: {total_day_time}", 
                        font=('Helvetica', 12, 'bold'),
                        bg='#34495e', fg='#3498db').pack(side='left')
                
                # Delete day button
                tk.Button(day_header_frame, 
                         text="🗑️ Delete Day", 
                         font=('Helvetica', 8),
                         bg='#e74c3c', fg='white',
                         relief='flat', padx=8, pady=2,
                         command=lambda d=date: self.delete_day(d)).pack(side='right')
                
                # Exercises for day
                for data in days_data[date]:
                    exercise_frame = tk.Frame(day_frame, bg='#34495e')
                    exercise_frame.pack(fill='x', padx=20, pady=2)
                    
                    tk.Label(exercise_frame, 
                            text=f"🎸 {data['exercise']} - {data['time']} - {data['bpm']} BPM", 
                            font=('Helvetica', 10),
                            bg='#34495e', fg='#ecf0f1').pack(side='left')
            
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
        
        # Back button
        back_frame = tk.Frame(self.history_frame, bg='#34495e')
        back_frame.pack(pady=20)
        
        tk.Button(back_frame, 
                 text="🔙 Back", 
                 font=('Helvetica', 12, 'bold'),
                 bg='#95a5a6', fg='white',
                 relief='flat', padx=20, pady=10,
                 command=self.show_main_screen).pack()

    def delete_day(self, date):
        """Delete entire day of workouts"""
        day_workouts = [d for d in self.workout_data 
                       if datetime.fromisoformat(d['timestamp']).strftime('%d %B %Y') == date]
        if not day_workouts:
            messagebox.showinfo("Information", "No workouts found for this day!")
            return
        workout_list = "\n".join([f"• {w['exercise']} - {w['time']} - {w['bpm']} BPM" for w in day_workouts])
        if messagebox.askyesno("Delete Confirmation", 
                              f"Delete entire day {date}?\n\n{workout_list}\n\nTotal: {len(day_workouts)} workouts"):
            for workout in day_workouts:
                self.workout_data.remove(workout)
            self.save_data()
            self.update_total_time_display()
            self.view_history()
            messagebox.showinfo("Success", f"Day {date} deleted! Deleted {len(day_workouts)} workouts.")




    def show_exercise_stats(self, exercise_name):
        """Show exercise statistics"""
        # Filter data by exercise
        exercise_data = [data for data in self.workout_data if data['exercise'] == exercise_name]
        
        if len(exercise_data) < 1:
            messagebox.showinfo("Information", f"No data for exercise '{exercise_name}'")
            return
        
        # Get statistics
        stats = self.get_exercise_stats(exercise_name)
        best_bpm = self.get_best_bpm(exercise_name)
        
        # Create new window for statistics
        stats_window = tk.Toplevel(self.master)
        stats_window.title(f"📈 Statistics: {exercise_name}")
        stats_window.geometry("900x700")
        stats_window.configure(bg='#2c3e50')
        
        # Title
        tk.Label(stats_window, 
                text=f"📊 Exercise Statistics: {exercise_name}", 
                font=('Helvetica', 16, 'bold'),
                bg='#2c3e50', fg='#ecf0f1').pack(pady=20)
        
        # General Statistics
        stats_frame = tk.Frame(stats_window, bg='#34495e', relief='raised', bd=2)
        stats_frame.pack(fill='x', padx=20, pady=10)
        
        tk.Label(stats_frame, 
                text="📈 General Statistics", 
                font=('Helvetica', 14, 'bold'),
                bg='#34495e', fg='#3498db').pack(pady=10)
        
        # Statistics details
        details_frame = tk.Frame(stats_frame, bg='#34495e')
        details_frame.pack(pady=10, padx=20)
        
        tk.Label(details_frame, 
                text=f"🎯 Total Sessions: {stats['total_sessions']}", 
                font=('Helvetica', 12),
                bg='#34495e', fg='#ecf0f1').pack(anchor='w', pady=2)
        
        tk.Label(details_frame, 
                text=f"⏱️ Total Time: {stats['total_time_formatted']}", 
                font=('Helvetica', 12),
                bg='#34495e', fg='#ecf0f1').pack(anchor='w', pady=2)
        
        tk.Label(details_frame, 
                text=f"📊 Best BPM: {best_bpm}", 
                font=('Helvetica', 12),
                bg='#34495e', fg='#ecf0f1').pack(anchor='w', pady=2)
        
        if len(exercise_data) >= 2:
            dates, bpms = [], []
            for data in sorted(exercise_data, key=lambda x: x['timestamp']):
                try:
                    if data['bpm'].isdigit():
                        dates.append(datetime.fromisoformat(data['timestamp']))
                        bpms.append(int(data['bpm']))
                except (ValueError, KeyError):
                    continue
            if len(dates) >= 2:
                fig, ax = plt.subplots(figsize=(10, 6))
                ax.plot(dates, bpms, 'o-', linewidth=2, markersize=8, color='#3498db')
                ax.set_title(f'Exercise Progress: {exercise_name}', fontsize=16, fontweight='bold')
                ax.set_xlabel('Date', fontsize=12)
                ax.set_ylabel('BPM', fontsize=12)
                ax.grid(True, alpha=0.3)
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
                plt.xticks(rotation=45)
                for date, bpm in zip(dates, bpms):
                    ax.annotate(f'{bpm}', (date, bpm), textcoords="offset points", xytext=(0,10), ha='center', fontsize=8)
                plt.tight_layout()
                canvas = FigureCanvasTkAgg(fig, stats_window)
                canvas.draw()
                canvas.get_tk_widget().pack(fill='both', expand=True, padx=20, pady=20)
            else:
                tk.Label(stats_window, text="📊 Not enough data to build chart", 
                        font=('Helvetica', 12), bg='#2c3e50', fg='#95a5a6').pack(pady=20)
        else:
            tk.Label(stats_window, text="📊 Not enough data to build chart", 
                    font=('Helvetica', 12), bg='#2c3e50', fg='#95a5a6').pack(pady=20)
        tk.Button(stats_window, text="🔙 Close", font=('Helvetica', 12, 'bold'), bg='#95a5a6', fg='white',
                 relief='flat', padx=20, pady=10, command=stats_window.destroy).pack(pady=20)

    def load_data(self):
        """Load data"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Parse data from markdown file
                    self.workout_data = []
                    lines = content.split('\n')
                    current_date = None
                    
                    for line in lines:
                        if line.startswith('## '):
                            current_date = line[3:].strip()
                        elif line.startswith('| ') and current_date and not line.startswith('| ---') and 'BPM' not in line:
                            parts = line.split('|')
                            if len(parts) >= 4:
                                exercise = parts[1].strip()
                                if exercise and not exercise.startswith('-') and exercise != 'Exercise Name':
                                    try:
                                        timestamp = datetime.strptime(current_date, '%d %B %Y').isoformat()
                                    except:
                                        timestamp = datetime.now().isoformat()
                                    self.workout_data.append({
                                        'exercise': exercise, 'time': parts[2].strip(), 'bpm': parts[3].strip(),
                                        'timestamp': timestamp
                                    })
            except Exception:
                self.workout_data = []

    def save_data(self):
        """Save data to markdown file"""
        try:
            days_data = self._group_data_by_days()
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.data_file) if os.path.dirname(self.data_file) else '.', exist_ok=True)
            # Write directly to file (flushed immediately)
            with open(self.data_file, 'w', encoding='utf-8') as f:
                f.write("# Guitar Exercises\n\n")
                
                if not days_data:
                    f.write("Workout history is empty.\n")
                else:
                    for date in self._sort_dates(days_data.keys()):
                        f.write(f"## {date}\n\n")
                        f.write("| Exercise Name | Time  | BPM |\n")
                        f.write("| ------------------- | ------ | --- |\n")
                        
                        for data in days_data[date]:
                            f.write(f"| {data['exercise']} | {data['time']} | {data['bpm']} |\n")
                        
                        f.write("\n")
                # Force flush to disk
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            # Silently fail - data will still be in memory
            print(f"Error saving data: {e}")


def main():
    root = tk.Tk()
    app = ModernGuitarTrainerV2(root)
    root.mainloop()

if __name__ == "__main__":
    main()
