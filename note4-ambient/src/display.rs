use image::{DynamicImage, GrayImage};
use zectrix_sdk::DeviceStatus;

fn set_pixel(image: &mut GrayImage, x: i32, y: i32, value: u8) {
    if x >= 0 && y >= 0 && x < image.width() as i32 && y < image.height() as i32 {
        image.put_pixel(x as u32, y as u32, image::Luma([value]));
    }
}

fn fill_rect(image: &mut GrayImage, x: i32, y: i32, width: i32, height: i32, value: u8) {
    for py in y..y + height {
        for px in x..x + width {
            set_pixel(image, px, py, value);
        }
    }
}

fn outline_rect(image: &mut GrayImage, x: i32, y: i32, width: i32, height: i32, value: u8) {
    fill_rect(image, x, y, width, 1, value);
    fill_rect(image, x, y + height - 1, width, 1, value);
    fill_rect(image, x, y, 1, height, value);
    fill_rect(image, x + width - 1, y, 1, height, value);
}

fn glyph(character: char) -> [u8; 7] {
    match character {
        '0' => [14, 17, 19, 21, 25, 17, 14],
        '1' => [4, 12, 4, 4, 4, 4, 14],
        '2' => [14, 17, 1, 2, 4, 8, 31],
        '3' => [30, 1, 1, 14, 1, 1, 30],
        '4' => [2, 6, 10, 18, 31, 2, 2],
        '5' => [31, 16, 16, 30, 1, 1, 30],
        '6' => [14, 16, 16, 30, 17, 17, 14],
        '7' => [31, 1, 2, 4, 8, 8, 8],
        '8' => [14, 17, 17, 14, 17, 17, 14],
        '9' => [14, 17, 17, 15, 1, 1, 14],
        '%' => [17, 2, 2, 4, 8, 8, 17],
        '-' => [0, 0, 0, 31, 0, 0, 0],
        _ => [0; 7],
    }
}

fn draw_text_scaled(image: &mut GrayImage, x: i32, y: i32, text: &str, value: u8, scale: i32) {
    for (index, character) in text.chars().enumerate() {
        for (row, bits) in glyph(character).into_iter().enumerate() {
            for column in 0..5 {
                if bits & (1 << (4 - column)) != 0 {
                    fill_rect(image, x + (index as i32 * 6 + column) * scale, y + row as i32 * scale, scale, scale, value);
                }
            }
        }
    }
}

fn draw_text(image: &mut GrayImage, x: i32, y: i32, text: &str, value: u8) {
    draw_text_scaled(image, x, y, text, value, 1);
}

fn fill_rounded_rect(image: &mut GrayImage, x: i32, y: i32, width: i32, height: i32, radius: i32, value: u8) {
    for py in y..y + height {
        for px in x..x + width {
            let nearest_x = px.clamp(x + radius, x + width - radius - 1);
            let nearest_y = py.clamp(y + radius, y + height - radius - 1);
            if (px - nearest_x).pow(2) + (py - nearest_y).pow(2) <= radius * radius {
                set_pixel(image, px, py, value);
            }
        }
    }
}

fn draw_status(image: &mut GrayImage, status: &DeviceStatus) {
    let ink = 45;
    let inactive = 180;
    fill_rounded_rect(image, 281, 30, 91, 24, 5, 248);
    if status.charging == Some(true) {
        fill_rect(image, 283, 41, 5, 1, ink);
        fill_rect(image, 285, 39, 1, 5, ink);
    }
    outline_rect(image, 291, 37, 15, 10, ink);
    fill_rect(image, 306, 40, 2, 4, ink);
    if let Some(percent) = status.battery_percent {
        fill_rect(image, 293, 39, (percent as i32 * 11 + 50) / 100, 6, ink);
        draw_text(image, 312, 39, &format!("{percent}%"), ink);
    } else {
        draw_text(image, 312, 39, "--", ink);
    }
    let strength = match status.wifi_rssi_dbm {
        Some(rssi) if rssi >= -55 => 3,
        Some(rssi) if rssi >= -67 => 2,
        Some(_) => 1,
        None => 0,
    };
    for index in 0..3 {
        let height = 4 + index * 3;
        fill_rect(image, 349 + index * 6, 47 - height, 3, height, if index < strength { ink } else { inactive });
    }
}

fn draw_volume(image: &mut GrayImage, volume: u8) {
    let level = ((volume as i32 + 12) / 25).min(4);
    fill_rounded_rect(image, 20, 261, 64, 26, 6, 248);
    fill_rounded_rect(image, 28, 269, 13, 11, 4, 45);
    fill_rounded_rect(image, 34, 264, 10, 10, 4, 45);
    for row in 0_i32..4 {
        fill_rect(image, 44, 267 + row, 4 - row, 1, 45);
    }
    fill_rect(image, 31, 280, 1, 3, 45);
    fill_rect(image, 36, 280, 1, 3, 45);
    fill_rect(image, 30, 272, 5, 4, 130);
    if level == 0 {
        fill_rect(image, 38, 267, 3, 1, 248);
        fill_rect(image, 51, 265, 7, 1, 45);
        fill_rect(image, 51, 271, 7, 1, 45);
        for index in 0_i32..6 {
            set_pixel(image, 56 - index, 266 + index, 45);
        }
    } else {
        set_pixel(image, 39, 267, 248);
        for index in 0_i32..level {
            let x = 50 + index * 8;
            let y = 264 + (index % 2) * 2;
            fill_rect(image, x, y + 4, 3, 3, 45);
            fill_rect(image, x + 2, y - 2, 1, 6, 45);
            if index % 2 == 1 {
                fill_rect(image, x + 3, y - 2, 3, 1, 45);
            }
        }
    }
}

pub fn render(png: &[u8], status: &DeviceStatus, volume: u8) -> Result<Vec<u8>, String> {
    let decoded = image::load_from_memory_with_format(png, image::ImageFormat::Png).map_err(|_| "无法解码状态栏原始 PNG")?;
    let mut image = decoded.to_luma8();
    if image.dimensions() != (400, 300) {
        return Err("状态栏原始图片必须为 400×300".into());
    }
    draw_status(&mut image, status);
    draw_volume(&mut image, volume);
    let mut output = std::io::Cursor::new(Vec::new());
    DynamicImage::ImageLuma8(image).write_to(&mut output, image::ImageFormat::Png).map_err(|_| "无法编码状态栏 PNG")?;
    Ok(output.into_inner())
}
