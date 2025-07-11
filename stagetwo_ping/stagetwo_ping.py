import time
import board
import displayio
import terminalio
from adafruit_display_text import label
import wifi
import socketpool
import adafruit_requests
import random

# --- Graphics and Game Constants ---
DISPLAY_WIDTH = 240
DISPLAY_HEIGHT = 135
PADDLE_WIDTH = 8
PADDLE_HEIGHT = 35
BALL_RADIUS = 4
BALL_COLOR = 0x00FF00
CLIENT_PADDLE_COLOR = 0x00FFFF  # Cyan for client
HOST_PADDLE_COLOR = 0xFF00FF    # Magenta for host
BG_COLOR = 0x000000
TEXT_COLOR = 0xFFFFFF
SCORE_COLOR = 0xFFFF00

# Game settings
MAX_SCORE = 5
PING_UPDATE_INTERVAL = 300  # Update ping every 300 frames (~15 seconds at 20fps)
FRAME_DELAY = 0.03  # Faster frame rate for smoother animation

# --- WiFi Setup ---
WIFI_SSID = "Access 316"
WIFI_PASSWORD = "ZaiyEden2024!"
PING_HOST = "8.8.8.8"  # Single host for speed

# Connect to WiFi
print("Connecting to WiFi...")
wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
print(f"Connected to {WIFI_SSID}")

pool = socketpool.SocketPool(wifi.radio)

# --- Setup Display ---
display = board.DISPLAY
main_group = displayio.Group()
display.root_group = main_group

# Create background
bg_bitmap = displayio.Bitmap(DISPLAY_WIDTH, DISPLAY_HEIGHT, 1)
bg_palette = displayio.Palette(1)
bg_palette[0] = BG_COLOR
bg_tilegrid = displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette)
main_group.append(bg_tilegrid)

# --- Create Center Line ---
center_line_bitmap = displayio.Bitmap(2, DISPLAY_HEIGHT, 2)
center_line_palette = displayio.Palette(2)
center_line_palette[0] = BG_COLOR
center_line_palette[1] = 0x444444  # Dark gray
for y in range(0, DISPLAY_HEIGHT, 8):
    for i in range(min(4, DISPLAY_HEIGHT - y)):
        if y + i < DISPLAY_HEIGHT:
            center_line_bitmap[0, y + i] = 1
            center_line_bitmap[1, y + i] = 1
center_line_tilegrid = displayio.TileGrid(center_line_bitmap, pixel_shader=center_line_palette, 
                                         x=DISPLAY_WIDTH//2 - 1, y=0)
main_group.append(center_line_tilegrid)

# --- Client Paddle (Left - controlled by ping) ---
client_paddle_bitmap = displayio.Bitmap(PADDLE_WIDTH, PADDLE_HEIGHT, 2)
client_paddle_palette = displayio.Palette(2)
client_paddle_palette[0] = BG_COLOR
client_paddle_palette[1] = CLIENT_PADDLE_COLOR
for y in range(PADDLE_HEIGHT):
    for x in range(PADDLE_WIDTH):
        client_paddle_bitmap[x, y] = 1
client_paddle_tilegrid = displayio.TileGrid(client_paddle_bitmap, pixel_shader=client_paddle_palette, 
                                           x=10, y=(DISPLAY_HEIGHT - PADDLE_HEIGHT)//2)
main_group.append(client_paddle_tilegrid)

# --- Host Paddle (Right - AI controlled) ---
host_paddle_bitmap = displayio.Bitmap(PADDLE_WIDTH, PADDLE_HEIGHT, 2)
host_paddle_palette = displayio.Palette(2)
host_paddle_palette[0] = BG_COLOR
host_paddle_palette[1] = HOST_PADDLE_COLOR
for y in range(PADDLE_HEIGHT):
    for x in range(PADDLE_WIDTH):
        host_paddle_bitmap[x, y] = 1
host_paddle_tilegrid = displayio.TileGrid(host_paddle_bitmap, pixel_shader=host_paddle_palette, 
                                         x=DISPLAY_WIDTH - PADDLE_WIDTH - 10, y=(DISPLAY_HEIGHT - PADDLE_HEIGHT)//2)
main_group.append(host_paddle_tilegrid)

# --- Ball ---
ball_bitmap = displayio.Bitmap(BALL_RADIUS*2, BALL_RADIUS*2, 2)
ball_palette = displayio.Palette(2)
ball_palette[0] = BG_COLOR
ball_palette[1] = BALL_COLOR
for y in range(BALL_RADIUS*2):
    for x in range(BALL_RADIUS*2):
        if (x-BALL_RADIUS)**2 + (y-BALL_RADIUS)**2 <= BALL_RADIUS**2:
            ball_bitmap[x, y] = 1
ball_tilegrid = displayio.TileGrid(ball_bitmap, pixel_shader=ball_palette, 
                                  x=DISPLAY_WIDTH//2 - BALL_RADIUS, y=DISPLAY_HEIGHT//2 - BALL_RADIUS)
main_group.append(ball_tilegrid)

# --- UI Elements ---
# Player labels
client_label = label.Label(terminalio.FONT, text="CLIENT", color=CLIENT_PADDLE_COLOR, x=5, y=10)
main_group.append(client_label)

host_label = label.Label(terminalio.FONT, text="HOST", color=HOST_PADDLE_COLOR, x=DISPLAY_WIDTH - 35, y=10)
main_group.append(host_label)

# Score display
client_score_label = label.Label(terminalio.FONT, text="0", color=SCORE_COLOR, x=50, y=10)
main_group.append(client_score_label)

host_score_label = label.Label(terminalio.FONT, text="0", color=SCORE_COLOR, x=DISPLAY_WIDTH - 60, y=10)
main_group.append(host_score_label)

# Ping display
ping_label = label.Label(terminalio.FONT, text="Ping: -- ms", color=TEXT_COLOR, x=70, y=25)
main_group.append(ping_label)

# Performance indicator
perf_label = label.Label(terminalio.FONT, text="Performance: Good", color=0x00FF00, x=5, y=DISPLAY_HEIGHT - 15)
main_group.append(perf_label)

# Game status
status_label = label.Label(terminalio.FONT, text="", color=TEXT_COLOR, x=60, y=DISPLAY_HEIGHT//2 + 20)
main_group.append(status_label)

# --- Game State ---
ball_dx = 2.5
ball_dy = 1.5
client_score = 0
host_score = 0
game_state = "playing"  # "playing", "paused", "game_over"
last_ping = 50
ping_history = [50, 50, 50]  # Initialize with default values
performance_rating = "Good"
ping_counter = 0
ball_speed_multiplier = 1.0
status_timer = 0

# Smooth paddle movement variables
client_paddle_target_y = (DISPLAY_HEIGHT - PADDLE_HEIGHT)//2
client_paddle_velocity = 0
host_paddle_target_y = (DISPLAY_HEIGHT - PADDLE_HEIGHT)//2
host_paddle_velocity = 0

def quick_ping():
    """Quick ping using socket connection - non-blocking approach"""
    global last_ping, ping_history, performance_rating
    
    try:
        start_time = time.monotonic()
        sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
        sock.settimeout(0.5)  # Very short timeout
        sock.connect((PING_HOST, 53))  # DNS port
        end_time = time.monotonic()
        sock.close()
        
        ping_ms = int((end_time - start_time) * 1000)
        last_ping = min(ping_ms, 300)  # Cap at 300ms
        
        # Update ping history
        ping_history.append(last_ping)
        if len(ping_history) > 5:  # Keep smaller history for responsiveness
            ping_history.pop(0)
        
        # Calculate performance rating
        avg_ping = sum(ping_history) / len(ping_history)
        ping_variance = sum((p - avg_ping) ** 2 for p in ping_history) / len(ping_history)
        
        if avg_ping < 50 and ping_variance < 100:
            performance_rating = "Excellent"
            perf_label.color = 0x00FF00
        elif avg_ping < 100 and ping_variance < 400:
            performance_rating = "Good"
            perf_label.color = 0x88FF00
        elif avg_ping < 200:
            performance_rating = "Fair"
            perf_label.color = 0xFFFF00
        else:
            performance_rating = "Poor"
            perf_label.color = 0xFF0000
            
    except Exception as e:
        # Don't print errors to avoid slowing down - just use last known ping
        pass
    
    return last_ping

def update_client_paddle():
    """Smooth client paddle movement based on ping performance"""
    global client_paddle_target_y, client_paddle_velocity
    
    # Calculate target based on ball position and ping performance
    base_target = ball_tilegrid.y + BALL_RADIUS - PADDLE_HEIGHT//2
    
    # Add ping-based effects
    if last_ping < 50:
        # Excellent - very responsive
        ping_offset = random.randint(-2, 2)
        max_speed = 4
    elif last_ping < 100:
        # Good - slight lag
        ping_offset = random.randint(-8, 8)
        max_speed = 3
    elif last_ping < 200:
        # Fair - noticeable lag
        ping_offset = random.randint(-15, 15)
        max_speed = 2
    else:
        # Poor - significant lag
        ping_offset = random.randint(-25, 25)
        max_speed = 1
    
    client_paddle_target_y = base_target + ping_offset
    
    # Smooth movement with physics-like acceleration
    target_diff = client_paddle_target_y - client_paddle_tilegrid.y
    client_paddle_velocity += target_diff * 0.1  # Acceleration
    client_paddle_velocity *= 0.8  # Damping
    client_paddle_velocity = max(-max_speed, min(max_speed, client_paddle_velocity))
    
    # Update position
    new_y = client_paddle_tilegrid.y + client_paddle_velocity
    client_paddle_tilegrid.y = max(0, min(DISPLAY_HEIGHT - PADDLE_HEIGHT, int(new_y)))

def update_host_paddle():
    """Smooth host paddle AI movement"""
    global host_paddle_target_y, host_paddle_velocity
    
    # AI targets ball with slight imperfection
    host_paddle_target_y = ball_tilegrid.y + BALL_RADIUS - PADDLE_HEIGHT//2
    
    # Add occasional AI mistakes
    if random.randint(1, 30) == 1:
        host_paddle_target_y += random.randint(-20, 20)
    
    # Smooth movement
    target_diff = host_paddle_target_y - host_paddle_tilegrid.y
    host_paddle_velocity += target_diff * 0.12  # Slightly better than client
    host_paddle_velocity *= 0.8
    host_paddle_velocity = max(-3, min(3, host_paddle_velocity))
    
    new_y = host_paddle_tilegrid.y + host_paddle_velocity
    host_paddle_tilegrid.y = max(0, min(DISPLAY_HEIGHT - PADDLE_HEIGHT, int(new_y)))

def reset_ball():
    """Reset ball to center with random direction"""
    global ball_dx, ball_dy
    ball_tilegrid.x = DISPLAY_WIDTH//2 - BALL_RADIUS
    ball_tilegrid.y = DISPLAY_HEIGHT//2 - BALL_RADIUS
    ball_dx = random.choice([-2.5, 2.5])
    ball_dy = random.choice([-1.5, 1.5])

def check_game_over():
    """Check if game is over and update status"""
    global game_state, status_timer
    if client_score >= MAX_SCORE:
        game_state = "game_over"
        status_label.text = "CLIENT WINS!"
        status_label.color = CLIENT_PADDLE_COLOR
        status_timer = 0
    elif host_score >= MAX_SCORE:
        game_state = "game_over"
        status_label.text = "HOST WINS!"
        status_label.color = HOST_PADDLE_COLOR
        status_timer = 0

# Initialize game
reset_ball()

# --- Main Game Loop ---
while True:
    if game_state == "playing":
        # Update ping very infrequently to avoid stuttering
        if ping_counter % PING_UPDATE_INTERVAL == 0:
            current_ping = quick_ping()
            ping_label.text = f"Ping: {current_ping} ms"
            perf_label.text = f"Perf: {performance_rating}"
        
        # Update paddles with smooth movement
        update_client_paddle()
        update_host_paddle()
        
        # Move ball with floating point precision
        ball_tilegrid.x += int(ball_dx * ball_speed_multiplier)
        ball_tilegrid.y += int(ball_dy * ball_speed_multiplier)
        
        # Ball collision with top/bottom walls
        if ball_tilegrid.y <= 0 or ball_tilegrid.y >= DISPLAY_HEIGHT - BALL_RADIUS*2:
            ball_dy *= -1
            ball_tilegrid.y = max(0, min(DISPLAY_HEIGHT - BALL_RADIUS*2, ball_tilegrid.y))
        
        # Ball collision with client paddle (left)
        if (ball_tilegrid.x <= client_paddle_tilegrid.x + PADDLE_WIDTH and
            ball_tilegrid.x >= client_paddle_tilegrid.x - BALL_RADIUS and
            client_paddle_tilegrid.y <= ball_tilegrid.y + BALL_RADIUS*2 and
            ball_tilegrid.y <= client_paddle_tilegrid.y + PADDLE_HEIGHT):
            ball_dx = abs(ball_dx) + 0.2  # Increase speed slightly
            ball_tilegrid.x = client_paddle_tilegrid.x + PADDLE_WIDTH
            # Add spin based on paddle velocity
            ball_dy += client_paddle_velocity * 0.3
            ball_speed_multiplier = min(ball_speed_multiplier + 0.05, 1.8)
        
        # Ball collision with host paddle (right)
        if (ball_tilegrid.x + BALL_RADIUS*2 >= host_paddle_tilegrid.x and
            ball_tilegrid.x <= host_paddle_tilegrid.x + PADDLE_WIDTH + BALL_RADIUS and
            host_paddle_tilegrid.y <= ball_tilegrid.y + BALL_RADIUS*2 and
            ball_tilegrid.y <= host_paddle_tilegrid.y + PADDLE_HEIGHT):
            ball_dx = -(abs(ball_dx) + 0.2)  # Increase speed slightly
            ball_tilegrid.x = host_paddle_tilegrid.x - BALL_RADIUS*2
            # Add spin based on paddle velocity
            ball_dy += host_paddle_velocity * 0.3
            ball_speed_multiplier = min(ball_speed_multiplier + 0.05, 1.8)
        
        # Ball out of bounds - scoring
        if ball_tilegrid.x < -BALL_RADIUS*2:
            # Host scores
            host_score += 1
            host_score_label.text = str(host_score)
            reset_ball()
            ball_speed_multiplier = 1.0
            status_label.text = "HOST SCORES!"
            status_label.color = HOST_PADDLE_COLOR
            status_timer = 120  # Show message for 120 frames
            
        elif ball_tilegrid.x > DISPLAY_WIDTH:
            # Client scores
            client_score += 1
            client_score_label.text = str(client_score)
            reset_ball()
            ball_speed_multiplier = 1.0
            status_label.text = "CLIENT SCORES!"
            status_label.color = CLIENT_PADDLE_COLOR
            status_timer = 120  # Show message for 120 frames
        
        # Clear status message after timer expires
        if status_timer > 0:
            status_timer -= 1
            if status_timer == 0:
                status_label.text = ""
        
        # Check for game over

        check_game_over()    
    elif game_state == "game_over":
        # Game over state - show final stats
        status_timer += 1
        
        # Flash the winner message
        if status_timer % 60 < 30:  # Flash every 60 frames
            if client_score >= MAX_SCORE:
                status_label.text = "CLIENT WINS!"
                status_label.color = CLIENT_PADDLE_COLOR
            else:
                status_label.text = "HOST WINS!"
                status_label.color = HOST_PADDLE_COLOR
        else:
            status_label.text = ""
        
        # Show final performance stats
        if ping_history:
            avg_ping = sum(ping_history) / len(ping_history)
            perf_label.text = f"Final: {int(avg_ping)}ms {performance_rating}"
        
        # Reset game after showing results
        if status_timer >= 600:  # Reset after ~30 seconds at 20fps
            client_score = 0
            host_score = 0
            client_score_label.text = "0"
            host_score_label.text = "0"
            game_state = "playing"
            reset_ball()
            ping_counter = 0
            status_timer = 0
            ball_speed_multiplier = 1.0
            status_label.text = "NEW GAME!"
            status_label.color = TEXT_COLOR
            # Reset paddle positions
            client_paddle_tilegrid.y = (DISPLAY_HEIGHT - PADDLE_HEIGHT)//2
            host_paddle_tilegrid.y = (DISPLAY_HEIGHT - PADDLE_HEIGHT)//2
            client_paddle_velocity = 0
            host_paddle_velocity = 0
    
    ping_counter += 1
    display.refresh()
    time.sleep(FRAME_DELAY)  # Faster, more consistent frame rate
