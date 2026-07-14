# Clawdmeter สำหรับ Sunton 2432S028 (CYD)

Clawdmeter คือจอ ESP32 ตั้งโต๊ะที่แสดงการใช้งาน Claude Code, Codex และ
ผู้ให้บริการที่รองรับอื่น ๆ แบบอัปเดตผ่าน Bluetooth Low Energy (BLE)
คอมพิวเตอร์ของคุณรัน daemon เพื่ออ่านข้อมูลการใช้งาน แล้วส่งไปยังจอชื่อ
**Clawdmeter** ทุกประมาณ 60 วินาที

README นี้ตั้งใจเขียนสำหรับ **Sunton ESP32-2432S028 / Cheap Yellow Display
(CYD) เท่านั้น** เพื่อให้เลือกไฟล์ firmware และติดตั้งได้ง่ายบน Windows

| หน้าจอ Usage | หน้าจอ Splash |
| :---: | :---: |
| ![หน้าจอ Usage](assets/demo.jpeg) | ![หน้าจอ Splash](assets/demo.gif) |

## ต้องมีอะไรบ้าง

- บอร์ด Sunton ESP32-2432S028 / CYD 2.8 นิ้ว และสาย USB **ที่รับส่งข้อมูลได้**
- คอมพิวเตอร์ Windows 10/11 ที่มี Bluetooth
- Python 3.11 ขึ้นไป (เฉพาะการติดตั้ง daemon หรือ flash แบบ command line)
- บัญชี Claude Code, Codex หรือ provider ที่ต้องการดู usage

## เลือก firmware ให้ถูกจอ

บอร์ด 2432S028 หน้าตาคล้ายกันมาก แต่ใช้ไดรเวอร์จอคนละแบบ หากเลือกผิดจอ
อาจขาว ดำ หรือไม่แสดงผล แม้ upload จะสำเร็จ

ให้เริ่มจากไฟล์ **Landscape** ก่อน หากต้องการวางจอแนวนอน:

| Panel ที่คาดว่าใช้ | Environment | ไฟล์ใน release |
| --- | --- | --- |
| R ปกติ — ILI9341 | `sunton_2432s028r_landscape` | `Clawdmeter-sunton_2432s028r_landscape-v0.2.1-factory.bin` |
| R v2 — ILI9341, init sequence อื่น | `sunton_2432s028rv2_landscape` | `Clawdmeter-sunton_2432s028rv2_landscape-v0.2.1-factory.bin` |
| R v3 — ST7789 | `sunton_2432s028rv3_landscape` | `Clawdmeter-sunton_2432s028rv3_landscape-v0.2.1-factory.bin` |

มี environment แนวตั้งสำหรับแต่ละรุ่นด้วย โดยตัดท้าย `_landscape` ออก:
`sunton_2432s028r`, `sunton_2432s028rv2`, และ `sunton_2432s028rv3`

> สำหรับบอร์ดที่เชื่อมต่ออยู่ในเครื่องนี้ รุ่นที่แสดงผลได้คือ
> **`sunton_2432s028r_landscape`** (ILI9341) ไม่ใช่ v3/ST7789

หากยังไม่รู้รุ่น ให้ลองตามลำดับ **R → R v2 → R v3** โดยใช้แนวเดียวกัน
เสมอ และหยุดทันทีเมื่อจอแสดงผลปกติ

## วิธีที่ง่ายที่สุด: flash จาก GitHub Release

1. เปิดหน้า [Releases](https://github.com/0xstillb/Clawdmeter/releases/latest)
2. ดาวน์โหลดไฟล์ที่ลงท้าย `-factory.bin` ให้ตรงกับตารางด้านบน
3. ต่อบอร์ดเข้าคอมพิวเตอร์ด้วยสาย USB data
4. ดูพอร์ตใน **Device Manager → Ports (COM & LPT)** เช่น `COM7`
5. เปิด PowerShell ในโฟลเดอร์ที่ดาวน์โหลดไฟล์ แล้วสั่ง:

```powershell
# ติดตั้ง esptool เพียงครั้งแรก
py -m pip install esptool

# ตัวอย่าง: รุ่น R จอ ILI9341 แนวนอนบน COM7
py -m esptool --chip esp32 --port COM7 --baud 460800 write-flash `
  --flash-mode dio --flash-freq 40m --flash-size 4MB 0x0 `
  .\Clawdmeter-sunton_2432s028r_landscape-v0.2.1-factory.bin
```

คำสั่งจะลบ firmware เก่าที่จำเป็นและเขียน image แบบครบชุด จากนั้นบอร์ดจะ
restart เอง หากขึ้น `Hash of data verified` แปลว่า flash สำเร็จ

หากขึ้น `Failed to connect` ให้กดค้างปุ่ม **BOOT**, กดปุ่ม **RST** หนึ่งครั้ง,
ปล่อย RST แล้วปล่อย BOOT เมื่อเริ่มเห็นข้อความ `Connecting` จากนั้นสั่งใหม่

## Build และ flash จาก source

วิธีนี้เหมาะเมื่อแก้ firmware เอง

### 1. ติดตั้ง PlatformIO

```powershell
py -m pip install platformio
```

เปิด PowerShell ที่โฟลเดอร์โปรเจกต์ แล้ว build ก่อนหนึ่งครั้ง:

```powershell
# รุ่น R / ILI9341 แนวนอน (แนะนำให้เริ่มจากตัวนี้)
pio run -d firmware -e sunton_2432s028r_landscape
```

### 2. Flash เข้า ESP32

เปลี่ยน `COM7` ให้เป็นพอร์ตของบอร์ด:

```powershell
# R / ILI9341 แนวนอน
pio run -d firmware -e sunton_2432s028r_landscape -t upload --upload-port COM7

# R v2 / ILI9341 แนวนอน
pio run -d firmware -e sunton_2432s028rv2_landscape -t upload --upload-port COM7

# R v3 / ST7789 แนวนอน
pio run -d firmware -e sunton_2432s028rv3_landscape -t upload --upload-port COM7
```

หากต้องการแนวตั้ง ให้เปลี่ยน environment เป็นชื่อที่ไม่มี `_landscape`

หลัง build เสร็จ PlatformIO จะสร้างไฟล์พร้อม flash เองที่:

```text
firmware/.pio/build/<environment>/firmware.factory.bin
```

ไฟล์ `firmware.factory.bin` เป็น image ครบชุด สำหรับ flash ที่ offset `0x0`
ตามตัวอย่างในหัวข้อก่อนหน้า ส่วน `firmware.bin` เป็น application-only และ
ควร flash ที่ offset `0x10000` เท่านั้น

## ตั้งค่า Bluetooth และใช้งานครั้งแรก

1. เมื่อ flash สำเร็จ บอร์ดจะโฆษณาชื่อ **Clawdmeter**
2. ไปที่ **Settings → Bluetooth & devices → Add device → Bluetooth**
3. เลือก `Clawdmeter` แล้ว Pair
4. แตะจอเพื่อสลับระหว่าง Splash และ Usage
5. ติดตั้ง daemon ตามหัวข้อถัดไป แล้วรอประมาณหนึ่งนาทีเพื่อรับข้อมูล usage

การ Pair สำคัญ เพราะบอร์ดยังทำงานเป็น BLE HID keyboard สำหรับปุ่มบนบอร์ดด้วย

## ติดตั้ง daemon บน Windows

Daemon ทำงานจาก system tray และเริ่มอัตโนมัติเมื่อ sign in

### ทางลัด

ดับเบิลคลิก:

```text
scripts\windows\Start Clawdmeter.cmd
```

สคริปต์จะสร้าง `.venv`, ติดตั้ง dependency, เปิด daemon และตั้งให้เริ่มหลัง
log in โดยอัตโนมัติ

### หรือสั่งเองใน PowerShell

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1
```

หลังติดตั้ง ให้มองหาไอคอน Clawdmeter ที่ system tray:

- สีเขียว: เชื่อมต่อและ sync สำเร็จ
- สีเหลือง: กำลังค้นหาบอร์ด
- สีแดง: มีข้อผิดพลาด — เอาเมาส์วางบนไอคอนเพื่ออ่านข้อความ

คลิกขวาที่ไอคอนเพื่อเลือก provider และตั้งค่า credential:

- **Codex / Claude** — อ่าน token ที่ login ไว้ในเครื่องโดยอัตโนมัติ
- **MiniMax Settings...** — กรอก Coding Plan API Key ที่ขึ้นต้นด้วย `sk-cp-`
- **DeepSeek API Key...** — กรอก API key เพื่อดูยอดคงเหลือ พร้อม breakdown ของ paid / granted credit
- **OpenRouter API Key...** — กรอก API key
- **Zen Settings...** และ **OpenCode Go...** — ตั้งค่า provider เหล่านั้น

หลังแก้ credential ให้เลือก **Restart** จาก tray (หรือ Quit แล้วเปิด
`Start Clawdmeter.cmd` อีกครั้ง)

## Wi-Fi fallback เมื่อปิดคอม (เฉพาะ API key)

CYD สามารถดึง usage เองผ่าน Wi-Fi ได้เมื่อ daemon/BLE ไม่มีข้อมูลต่อเนื่อง
90 วินาที จึงใช้ดูยอดต่อได้แม้ปิดคอมพิวเตอร์อยู่ ขณะ daemon ส่งข้อมูลตามปกติ
BLE จะมีสิทธิ์ก่อน และ Wi-Fi จะปิดเพื่อลดการใช้วิทยุร่วมกัน

รองรับ direct API ใน firmware สำหรับ **DeepSeek, OpenRouter และ MiniMax**
เท่านั้น ส่วน **Claude, Codex, OpenCode Go และ Zen** ยังคงใช้ daemon ผ่าน BLE;
โดยเฉพาะ Go/Zen ต้องใช้ cookie กับ workspace ID จึงไม่เก็บ credential เหล่านั้น
ไว้บนบอร์ด

บน Windows ที่แฟลช firmware รุ่นนี้แล้ว ให้คลิกขวาไอคอน Clawdmeter ใน system tray
แล้วเลือก **Wi-Fi fallback…** กรอกชื่อ/รหัส Wi-Fi แล้วกด **Save to CYD**. ชื่อเครือข่าย
ที่ Windows กำลังใช้อยู่จะถูกตรวจพบอัตโนมัติ; API key และ provider จะเลือกจาก credential
ที่ตั้งค่าไว้ใน tray แล้วโดยอัตโนมัติ (DeepSeek, OpenRouter หรือ MiniMax) หากบอร์ดยังไม่เชื่อม
BLE ค่าจะรอส่งโดยอัตโนมัติเมื่อเชื่อมครั้งถัดไป; หลัง CYD ยืนยันรับค่า Windows จะลบสำเนา
credential ที่รอส่งออกเอง

เมื่อ CYD เชื่อม Wi-Fi สำเร็จขณะที่ Windows tray ยังเชื่อมผ่าน BLE อยู่ จะมี notification
**CYD Wi-Fi connected** ปรากฏใน Windows. หากปิดคอมอยู่ CYD ยังทำงานเองได้ตามปกติ แต่
แน่นอนว่าจะไม่มี Windows ให้แสดง notification ในขณะนั้น

หรือจะตั้งค่าผ่าน USB serial monitor (เช่น `pio device monitor -p COM7 -b 115200`)
ก็ได้ โดยพิมพ์ทีละคำสั่ง:

```text
wifi network ชื่อWiFi รหัสผ่านWiFi
wifi provider deepseek API_KEY
# หรือ: wifi provider openrouter API_KEY
# หรือ: wifi provider minimax API_KEY
wifi status
```

SSID และรหัสผ่านในคำสั่งนี้ต้องไม่มีช่องว่าง; พิมพ์ `wifi help` เพื่อดูคำสั่ง
และ `wifi clear` เพื่อลบข้อมูลทั้งหมด การเชื่อมต่อไปยัง provider ใช้ HTTPS พร้อม
ตรวจสอบใบรับรอง แต่ API key และ Wi-Fi password ถูกเก็บใน NVS ของ CYD เพื่อให้
บอร์ดทำงานเองหลังรีสตาร์ต—อย่าใช้กับบอร์ดที่ผู้อื่นเข้าถึงทางกายภาพได้

## การใช้งานจอ

- แตะจอเพื่อสลับ Splash ↔ Usage
- หน้า Usage แสดงเปอร์เซ็นต์ usage และเวลาที่ quota จะ reset
- บัญชี Codex ที่ส่งมาเฉพาะ quota รายสัปดาห์ จะแสดงการ์ด **Weekly** ใบเดียว
- ค่า usage จะเปลี่ยนเมื่อ daemon ส่งข้อมูลใหม่ โดยปกติทุกประมาณ 60 วินาที
- หากเปลี่ยนบอร์ด ให้ลบ `Clawdmeter` ตัวเก่าจาก Windows Bluetooth แล้ว Pair ใหม่

## อัปเดต firmware ในอนาคต

1. ดาวน์โหลด `-factory.bin` ของรุ่นและแนวหน้าจอเดิมจาก
   [Releases](https://github.com/0xstillb/Clawdmeter/releases/latest)
2. flash ที่ offset `0x0` ตามคำสั่งในหัวข้อแรก
3. restart daemon จาก system tray

## แก้ปัญหา

| อาการ | วิธีแก้ |
| --- | --- |
| จอขาวหรือจอดำหลัง flash | เลือก panel ผิด ให้ลอง R, R v2, R v3 ตามลำดับ โดยรักษาแนวหน้าจอเดิม |
| Flash ผ่านแต่จอหมุนผิด | เปลี่ยนไปใช้ environment ที่มี/ไม่มี `_landscape` ให้ตรงกับการวางจอ |
| `Failed to connect` ตอน flash | ใช้สาย USB data, ปิด serial monitor และใช้ BOOT + RST ตามขั้นตอนด้านบน |
| daemon หาอุปกรณ์ไม่เจอ | ตรวจว่า Pair แล้ว, เปิด Bluetooth, อยู่ในระยะ และลบ pairing เดิมก่อน Pair ใหม่เมื่อเปลี่ยนบอร์ด |
| ไม่มีข้อมูล usage | ตรวจว่า login provider บนเครื่องนี้แล้ว และดูข้อความ error จากไอคอน tray |
| MiniMax ไม่อัปเดต | เปิด `Credentials → MiniMax Settings...` แล้วใส่ Coding Plan API Key (`sk-cp-*`) ใหม่ |

## โครงสร้างโปรเจกต์

- `firmware/` — firmware ESP32 และ environment สำหรับ CYD
- `daemon/` — Windows tray daemon และ provider plugins
- `scripts/windows/` — ติดตั้งและเปิด daemon บน Windows
- `firmware/platformio.ini` — รายชื่อ environment ที่ใช้ build/flash

## Credits

- Pixel-art Clawd animation จาก [claudepix](https://claudepix.vercel.app)
- Lucide icons ([MIT License](https://lucide.dev/license))
