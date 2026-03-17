import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import os
from dotenv import load_dotenv
import pytz
# --- CẤU HÌNH ĐƯỜNG DẪN DATABASE CHO RENDER ---
# Render sẽ gắn đĩa lưu trữ vào đường dẫn này.
# Nếu biến môi trường RENDER_DISK_PATH tồn tại, dùng nó. Nếu không (chạy ở local), dùng thư mục hiện tại.
DATA_DIR = os.environ.get('RENDER_DISK_PATH', '.') 
DB_PATH = os.path.join(DATA_DIR, 'attendance.db')

print(f"--- Sử dụng database tại đường dẫn: {DB_PATH} ---")

# Tải các biến từ file .env
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Kiểm tra xem token có được tải thành công không
if TOKEN is None:
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    print("!!! LỖI: KHÔNG TÌM THẤY TOKEN TRONG FILE .env                !!!")
    print("!!! Vui lòng kiểm tra lại file .env của bạn và khởi động lại. !!!")
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    exit() # Dừng bot nếu không có token

print("--- Token đã được tải thành công. Chuẩn bị khởi động... ---")

# Cài đặt múi giờ Việt Nam
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

# Cài đặt Intents (quyền của bot)
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# Khởi tạo bot
bot = commands.Bot(command_prefix="!", intents=intents)

# --- QUẢN LÝ CƠ SỞ DỮ LIỆU (SQLITE) ---

def init_db():
    """Khởi tạo cơ sở dữ liệu và các bảng cần thiết."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Bảng lưu trữ thông tin chấm công
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            check_in_time TEXT,
            check_out_time TEXT
        )
    ''')
    # Bảng lưu trữ danh sách admin
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        )
    ''')
    conn.commit()
    conn.close()

def is_admin(user_id: int) -> bool:
    """Kiểm tra xem một user có phải là admin không."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# --- BOT EVENTS ---

@bot.event
async def on_ready():
    """Sự kiện khi bot đã sẵn sàng và kết nối thành công."""
    print(f'Đã đăng nhập với tên {bot.user}')
    init_db()  # Khởi tạo DB khi bot chạy
    try:
        synced = await bot.tree.sync()
        print(f"Đã đồng bộ {len(synced)} lệnh (/)")
    except Exception as e:
        print(f"Lỗi khi đồng bộ lệnh: {e}")

# --- CHECK PERMISSION CHO ADMIN ---

def is_bot_admin():
    """Hàm kiểm tra quyền admin cho các lệnh slash."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None: # Lệnh chỉ dùng trong server
            return False
        # Chủ server luôn là admin
        if interaction.user.id == interaction.guild.owner_id:
            return True
        # Kiểm tra trong DB
        if is_admin(interaction.user.id):
            return True
        
        await interaction.response.send_message("Bạn không có quyền sử dụng lệnh này.", ephemeral=True)
        return False
    return app_commands.check(predicate)

# --- LỆNH CHO MEMBER ---

@bot.tree.command(name="checkin", description="Bắt đầu phiên làm việc của bạn.")
async def checkin(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_name = interaction.user.display_name
    current_time = datetime.now(VIETNAM_TZ)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM attendance WHERE user_id = ? AND check_out_time IS NULL",
        (user_id,)
    )
    if cursor.fetchone():
        await interaction.response.send_message("Bạn đã check-in rồi. Vui lòng check-out trước khi check-in lại.", ephemeral=True)
        conn.close()
        return

    cursor.execute(
        "INSERT INTO attendance (user_id, user_name, check_in_time) VALUES (?, ?, ?)",
        (user_id, user_name, current_time.isoformat())
    )
    conn.commit()
    conn.close()

    embed = discord.Embed(
        title="✅ Check-in Thành Công!",
        description=f"Chào mừng **{user_name}** đã bắt đầu làm việc.",
        color=discord.Color.green()
    )
    embed.add_field(name="Thời gian", value=current_time.strftime('%H:%M:%S ngày %d-%m-%Y'))
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="checkout", description="Kết thúc phiên làm việc của bạn.")
async def checkout(interaction: discord.Interaction):
    user_id = interaction.user.id
    current_time = datetime.now(VIETNAM_TZ)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, check_in_time FROM attendance WHERE user_id = ? AND check_out_time IS NULL ORDER BY id DESC LIMIT 1",
        (user_id,)
    )
    record = cursor.fetchone()

    if not record:
        await interaction.response.send_message("Bạn chưa check-in. Vui lòng check-in trước.", ephemeral=True)
        conn.close()
        return

    record_id, check_in_time_str = record
    check_in_time = datetime.fromisoformat(check_in_time_str)

    cursor.execute(
        "UPDATE attendance SET check_out_time = ? WHERE id = ?",
        (current_time.isoformat(), record_id)
    )
    conn.commit()
    conn.close()

    duration = current_time - check_in_time
    hours, remainder = divmod(duration.total_seconds(), 3600)
    minutes, _ = divmod(remainder, 60)
    duration_str = f"{int(hours)} giờ {int(minutes)} phút"

    embed = discord.Embed(
        title="👋 Check-out Thành Công!",
        description=f"Tạm biệt **{interaction.user.display_name}**. Hẹn gặp lại!",
        color=discord.Color.orange()
    )
    embed.add_field(name="Thời gian Check-out", value=current_time.strftime('%H:%M:%S ngày %d-%m-%Y'))
    embed.add_field(name="Tổng thời gian làm việc", value=duration_str, inline=False)
    await interaction.response.send_message(embed=embed)

# --- LỆNH XEM LỊCH SỬ & THỐNG KÊ CÁ NHÂN ---

# Lệnh cho member tự xem thống kê
@bot.tree.command(name="mystats", description="Xem tổng thời gian làm việc của chính bạn.")
@app_commands.describe(period="Khoảng thời gian bạn muốn xem.")
@app_commands.choices(period=[
    Choice(name="Hôm nay", value="daily"),
    Choice(name="Tuần này", value="weekly"),
    Choice(name="Tháng này", value="monthly"),
])
async def mystats(interaction: discord.Interaction, period: str = "weekly"):
    await interaction.response.defer(ephemeral=True)

    user_id = interaction.user.id
    user_name = interaction.user.display_name
    now = datetime.now(VIETNAM_TZ)

    if period == "daily":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        period_str = f"hôm nay ({now.strftime('%d-%m-%Y')})"
    elif period == "monthly":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period_str = f"tháng này ({now.strftime('%m-%Y')})"
    else: # Mặc định là tuần
        start_date = now - timedelta(days=now.weekday())
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        period_str = f"tuần này"

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT check_in_time, check_out_time FROM attendance WHERE user_id = ? AND check_in_time >= ?",
        (user_id, start_date.isoformat())
    )
    records = cursor.fetchall()
    conn.close()

    if not records:
        await interaction.followup.send(f"Bạn không có dữ liệu chấm công nào trong {period_str}.", ephemeral=True)
        return

    total_duration = timedelta(0)
    for check_in_str, check_out_str in records:
        if check_out_str:
            check_in_time = datetime.fromisoformat(check_in_str)
            check_out_time = datetime.fromisoformat(check_out_str)
            total_duration += (check_out_time - check_in_time)

    hours, remainder = divmod(total_duration.total_seconds(), 3600)
    minutes, _ = divmod(remainder, 60)

    embed = discord.Embed(
        title=f"📊 Thống kê của {user_name}",
        description=f"Tổng hợp thời gian làm việc của bạn trong {period_str}.",
        color=interaction.user.color or discord.Color.green()
    )
    embed.add_field(
        name="Tổng thời gian đã ghi nhận",
        value=f"## {int(hours)} giờ {int(minutes)} phút",
        inline=False
    )
    embed.set_footer(text="Lưu ý: Chỉ các phiên đã check-out mới được tính.")
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# --- LỆNH CHO ADMIN ---

@bot.tree.command(name="status", description="[ADMIN] Xem những ai đang check-in.")
@is_bot_admin()
async def status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_name, check_in_time FROM attendance WHERE check_out_time IS NULL")
    active_users = cursor.fetchall()
    conn.close()

    if not active_users:
        await interaction.followup.send("Hiện tại không có ai đang check-in.")
        return

    embed = discord.Embed(
        title="📊 Trạng thái Check-in Hiện tại",
        description=f"Có **{len(active_users)}** thành viên đang làm việc.",
        color=discord.Color.blue()
    )
    
    for user_name, check_in_time_str in active_users:
        check_in_time = datetime.fromisoformat(check_in_time_str)
        embed.add_field(
            name=user_name,
            value=f"Check-in lúc: {check_in_time.strftime('%H:%M:%S')}",
            inline=False
        )
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="history", description="[ADMIN] Xem lịch sử chấm công chi tiết của một thành viên.")
@is_bot_admin()
@app_commands.describe(member="Thành viên bạn muốn xem lịch sử.", period="Khoảng thời gian xem.")
@app_commands.choices(period=[
    Choice(name="Hôm nay", value="daily"),
    Choice(name="Tuần này", value="weekly"),
    Choice(name="Tháng này", value="monthly"),
])
async def history(interaction: discord.Interaction, member: discord.Member, period: str = "weekly"):
    await interaction.response.defer(ephemeral=True)

    now = datetime.now(VIETNAM_TZ)
    if period == "daily":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        period_str = f"ngày {now.strftime('%d-%m-%Y')}"
    elif period == "monthly":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period_str = f"tháng {now.strftime('%m-%Y')}"
    else: # Mặc định là tuần
        start_date = now - timedelta(days=now.weekday())
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        period_str = f"tuần này"

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT check_in_time, check_out_time FROM attendance WHERE user_id = ? AND check_in_time >= ? ORDER BY check_in_time DESC",
        (member.id, start_date.isoformat())
    )
    records = cursor.fetchall()
    conn.close()

    if not records:
        await interaction.followup.send(f"Không tìm thấy dữ liệu chấm công của **{member.display_name}** trong {period_str}.", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"📜 Lịch sử Chấm công của {member.display_name}",
        description=f"Dữ liệu chi tiết trong {period_str}.",
        color=member.color or discord.Color.yellow()
    )

    history_text = ""
    total_duration = timedelta(0)
    for check_in_str, check_out_str in records:
        check_in_time = datetime.fromisoformat(check_in_str)
        day_str = check_in_time.strftime('%d/%m')
        
        if check_out_str:
            check_out_time = datetime.fromisoformat(check_out_str)
            duration = check_out_time - check_in_time
            total_duration += duration
            hours, rem = divmod(duration.seconds, 3600)
            mins, _ = divmod(rem, 60)
            duration_str = f"{int(hours)}h {int(mins)}m"
            history_text += f"**Ngày {day_str}**: `{check_in_time.strftime('%H:%M')}` - `{check_out_time.strftime('%H:%M')}` (**{duration_str}**)\n"
        else:
            history_text += f"**Ngày {day_str}**: `{check_in_time.strftime('%H:%M')}` - `🔴 CHƯA CHECK-OUT`\n"
    
    if len(history_text) > 3000:
        history_text = history_text[:3000] + "\n... (dữ liệu quá dài, đã được rút gọn)"

    embed.description += f"\n\n{history_text}"
    total_hours, rem = divmod(total_duration.total_seconds(), 3600)
    total_mins, _ = divmod(rem, 60)
    embed.set_footer(text=f"Tổng thời gian đã check-out: {int(total_hours)} giờ {int(total_mins)} phút")

    await interaction.followup.send(embed=embed, ephemeral=True)

# Lệnh báo cáo được nhóm lại
@app_commands.guild_only()
class ReportGroup(app_commands.Group, name="report", description="Các lệnh báo cáo chấm công."):

    @app_commands.command(name="daily", description="[ADMIN] Xem báo cáo chấm công trong ngày hôm nay.")
    @is_bot_admin()
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.defer()
        today = datetime.now(VIETNAM_TZ).date()
        start_of_day = datetime.combine(today, datetime.min.time(), tzinfo=VIETNAM_TZ)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_name, check_in_time, check_out_time FROM attendance WHERE check_in_time >= ?",
            (start_of_day.isoformat(),)
        )
        records = cursor.fetchall()
        conn.close()

        if not records:
            await interaction.followup.send("Hôm nay chưa có ai chấm công.")
            return

        report_data = {}
        checked_in_today = set()
        for user_name, check_in_str, check_out_str in records:
            checked_in_today.add(user_name)
            if check_out_str:
                duration = datetime.fromisoformat(check_out_str) - datetime.fromisoformat(check_in_str)
                report_data[user_name] = report_data.get(user_name, timedelta(0)) + duration

        embed = discord.Embed(
            title=f"📈 Báo cáo Chấm công Ngày {today.strftime('%d-%m-%Y')}",
            description=f"Tổng số người đã check-in hôm nay: **{len(checked_in_today)}**",
            color=discord.Color.purple()
        )

        if not report_data:
            embed.description += "\nChưa có ai hoàn thành phiên làm việc (check-out)."
        else:
            report_text = ""
            for user_name, total_duration in sorted(report_data.items()):
                hours, remainder = divmod(total_duration.total_seconds(), 3600)
                minutes, _ = divmod(remainder, 60)
                report_text += f"**{user_name}**: {int(hours)} giờ {int(minutes)} phút\n"
            embed.add_field(name="Tổng thời gian làm việc", value=report_text, inline=False)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="weekly", description="[ADMIN] Xem báo cáo chấm công trong 7 ngày qua.")
    @is_bot_admin()
    async def weekly(self, interaction: discord.Interaction):
        await interaction.response.defer()
        now = datetime.now(VIETNAM_TZ)
        seven_days_ago = now - timedelta(days=7)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_name, check_in_time, check_out_time FROM attendance WHERE check_in_time >= ?",
            (seven_days_ago.isoformat(),)
        )
        records = cursor.fetchall()
        conn.close()

        if not records:
            await interaction.followup.send("Không có dữ liệu chấm công nào trong 7 ngày qua.")
            return

        report_data = {}
        checked_in_this_week = set()
        for user_name, check_in_str, check_out_str in records:
            checked_in_this_week.add(user_name)
            if check_out_str:
                duration = datetime.fromisoformat(check_out_str) - datetime.fromisoformat(check_in_str)
                report_data[user_name] = report_data.get(user_name, timedelta(0)) + duration

        start_date_str = seven_days_ago.strftime('%d/%m')
        end_date_str = now.strftime('%d/%m/%Y')
        embed = discord.Embed(
            title=f"🗓️ Báo cáo Chấm công Tuần ({start_date_str} - {end_date_str})",
            description=f"Tổng số người đã làm việc trong 7 ngày qua: **{len(checked_in_this_week)}**",
            color=discord.Color.teal()
        )

        if not report_data:
            embed.description += "\nChưa có ai hoàn thành phiên làm việc (check-out) trong tuần."
        else:
            report_text = ""
            for user_name, total_duration in sorted(report_data.items()):
                hours, remainder = divmod(total_duration.total_seconds(), 3600)
                minutes, _ = divmod(remainder, 60)
                report_text += f"**{user_name}**: {int(hours)} giờ {int(minutes)} phút\n"
            embed.add_field(name="Tổng hợp thời gian làm việc", value=report_text, inline=False)
        await interaction.followup.send(embed=embed)

# --- LỆNH QUẢN LÝ ADMIN ---

@app_commands.guild_only()
class AdminManagement(app_commands.Group, name="admin", description="Quản lý vai trò admin của bot."):

    @app_commands.command(name="add", description="Thêm một người dùng làm admin bot.")
    @is_bot_admin()
    async def add(self, interaction: discord.Interaction, member: discord.Member):
        if is_admin(member.id):
            await interaction.response.send_message(f"{member.display_name} đã là admin rồi.", ephemeral=True)
            return
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO admins (user_id) VALUES (?)", (member.id,))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"✅ Đã thêm **{member.display_name}** vào danh sách admin.")

    @app_commands.command(name="remove", description="Xóa một người dùng khỏi vai trò admin bot.")
    @is_bot_admin()
    async def remove(self, interaction: discord.Interaction, member: discord.Member):
        if not is_admin(member.id):
            await interaction.response.send_message(f"{member.display_name} không phải là admin.", ephemeral=True)
            return

        if member.id == interaction.guild.owner_id:
            await interaction.response.send_message("Không thể xóa chủ server khỏi vai trò admin.", ephemeral=True)
            return
            
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM admins WHERE user_id = ?", (member.id,))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"🗑️ Đã xóa **{member.display_name}** khỏi danh sách admin.")

# --- Đăng ký các nhóm lệnh và chạy bot ---
bot.tree.add_command(AdminManagement())
bot.tree.add_command(ReportGroup())
bot.run(TOKEN)
 