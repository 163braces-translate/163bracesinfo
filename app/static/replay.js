/* 年度回顧：在瀏覽器裡用 Canvas 畫出 1080×1920 的回顧卡片。不會把任何輸入送回伺服器。
 * 從舊站 replay_page.html 原樣搬過來，只把模板變數改成讀頁面上的 JSON（replay-data），
 * 繪圖的部分沒有改。 */
(function () {
    // State management
    let selectedSongs = [];
    let selectedPerformances = [];
    let userName = '';
    let userMessage = '';
    // 頁面資料：stats.html 的 <script id="replay-data" type="application/json">
    const REPLAY = JSON.parse(document.getElementById('replay-data').textContent);
    const selectedYear = REPLAY.year;
    const currentLanguage = REPLAY.lang;
    const eventTypesData = REPLAY.eventTypes;
    const citiesData = REPLAY.cities;
    const logoUrl = REPLAY.logoUrl || null;

    // DOM elements
    const userNameInput = document.getElementById('userName');
    const songGrid = document.getElementById('songGrid');
    const performanceGrid = document.getElementById('performanceGrid');
    const generateBtn = document.getElementById('generateBtn');
    const previewSection = document.getElementById('previewSection');
    const canvas = document.getElementById('replayCanvas');
    const ctx = canvas.getContext('2d', { alpha: false });
    
    // High-DPI rendering
    const scale = 2; // Increase for higher quality
    canvas.width = 1080 * scale;
    canvas.height = 1920 * scale;
    canvas.style.width = '1080px';
    canvas.style.height = '1920px';
    ctx.scale(scale, scale);
    const downloadBtn = document.getElementById('downloadBtn');
    
    // Year change function
    function changeYear() {
        const selectedYear = document.getElementById('year-select').value;
        const currentUrl = new URL(window.location);
        currentUrl.searchParams.set('year', selectedYear);
        window.location.href = currentUrl.toString();
    }
    
    // User name input
    userNameInput.addEventListener('input', (e) => {
        userName = e.target.value.trim();
        updateGenerateButton();
    });
    
    // User message input（新增這段）
    const userMessageInput = document.getElementById('userMessage');
    const messageCount = document.getElementById('messageCount');

    userMessageInput.addEventListener('input', (e) => {
        userMessage = e.target.value.trim();
        messageCount.textContent = e.target.value.length;
        // 不需要 updateGenerateButton()，因為訊息不是必填
    });


    // Song selection (max 3)
    songGrid.addEventListener('click', (e) => {
        const card = e.target.closest('.song-card');
        if (!card) return;
        
        const songData = {
            id: card.dataset.id,
            title: card.dataset.title,
            titleEn: card.dataset.titleEn,
            artist: card.dataset.artist,
            artistEn: card.dataset.artistEn,
            album: card.dataset.album,
            imageUrl: card.dataset.imageUrl
        };
        
        const index = selectedSongs.findIndex(s => s.id === songData.id);
        
        if (index > -1) {
            selectedSongs.splice(index, 1);
            card.classList.remove('selected');
        } else if (selectedSongs.length < 3) {
            selectedSongs.push(songData);
            card.classList.add('selected');
        }
        
        updateSongBadges();
        updateGenerateButton();
    });
    
    // Performance selection (unlimited)
    performanceGrid.addEventListener('click', (e) => {
        const card = e.target.closest('.performance-card');
        if (!card) return;
        
        const perfData = {
            id: card.dataset.id,
            title: card.dataset.title,
            city: card.dataset.city,
            cityEn: card.dataset.cityEn,
            cityOrder: parseInt(card.dataset.cityOrder),
            type: card.dataset.performanceType,
            typeEn: card.dataset.performanceTypeEn,
            typeOrder: parseInt(card.dataset.performanceTypeOrder),
            date: card.dataset.date
        };
        
        const index = selectedPerformances.findIndex(p => p.id === perfData.id);
        
        if (index > -1) {
            selectedPerformances.splice(index, 1);
            card.classList.remove('selected');
        } else {
            selectedPerformances.push(perfData);
            card.classList.add('selected');
        }
        
        updatePerformanceCounts();
        updateGenerateButton();
    });
    
    function updateSongBadges() {
        const cards = songGrid.querySelectorAll('.song-card');
        cards.forEach(card => {
            const badge = card.querySelector('.selection-badge');
            const songId = card.dataset.id;
            const index = selectedSongs.findIndex(s => s.id === songId);
            
            if (index > -1) {
                badge.textContent = index + 1;
            } else {
                badge.textContent = '';
            }
        });
        
        document.getElementById('songCount').textContent = selectedSongs.length;
    }
    
    function updatePerformanceCounts() {
        document.getElementById('perfCount').textContent = selectedPerformances.length;
    }
    
    function updateGenerateButton() {
        const hasName = userName.length > 0;
        const hasSongs = selectedSongs.length > 0;
        
        // 有名字 AND 至少一首歌 → 可以生成
        generateBtn.disabled = !(hasName && hasSongs);
    }
    
    // Generate button click
    generateBtn.addEventListener('click', async () => {
        generateBtn.disabled = true;
        generateBtn.textContent = '⏳ 生成中... / Generating...';
        
        await generateReplayImage();

        // 將 Canvas 轉換成 Image（讓手機可以長按儲存）
        const resultImage = document.getElementById('resultImage');
        if (!resultImage) {
            // 第一次生成：建立 img 元素
            const img = document.createElement('img');
            img.id = 'resultImage';
            img.style.maxWidth = '100%';
            img.style.height = 'auto';
            img.style.borderRadius = '8px';
            img.style.boxShadow = '0 4px 8px rgba(0,0,0,0.1)';
            
            // 手機版調整尺寸
            if (window.innerWidth <= 768) {
                img.style.width = '400px';
            }
            
            // 將 img 插入到 canvas 後面
            canvas.parentNode.insertBefore(img, canvas.nextSibling);
            canvas.style.display = 'none';  // 隱藏 canvas
        }
        
        // 更新圖片內容
        document.getElementById('resultImage').src = canvas.toDataURL('image/png');
        
        previewSection.style.display = 'block';
        previewSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        
        generateBtn.textContent = '🎨 重新生成 / Regenerate';
        generateBtn.disabled = false;
    });
    
    // Download button
    downloadBtn.addEventListener('click', () => {
        const link = document.createElement('a');
        link.download = `${userName}_${selectedYear}_163braces_回顧.png`;
        
        // 從 resultImage 取得圖片，如果沒有就從 canvas 取得
        const resultImage = document.getElementById('resultImage');
        if (resultImage && resultImage.src) {
            link.href = resultImage.src;
        } else {
            link.href = canvas.toDataURL('image/png');
        }
        
        link.click();
    });


    // Generate the replay image
    async function generateReplayImage() {
        // Clear canvas with mint cream background
        ctx.fillStyle = '#f5fffa';
        ctx.fillRect(0, 0, 1080, 1920);
        
        // Draw logo in top-left corner
        if (logoUrl) {
            await drawLogo(ctx, logoUrl, 40, 40, 150); // x=40, y=40, maxWidth=150
        }

        // Title section
        ctx.fillStyle = '#333333';
        ctx.font = 'bold 64px "Source Sans 3", sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(`${userName} 的`, 540, 120);
        ctx.fillText(`${selectedYear} 年 163braces 回顧`, 540, 200);
        
        let yPos = 260;
        
        // Songs section
        if (selectedSongs.length > 0) {
            ctx.fillStyle = '#FFE4E1';
            drawRoundedRect(ctx, 80, yPos, 920, 50, 25);
            ctx.fillStyle = '#555555';
            ctx.font = 'bold 32px "Source Sans 3", sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('🎵 我的最愛歌曲', 540, yPos + 35);
            
            yPos += 80;
            
            // 橫向排列，模仿選擇時的卡片樣式
            const cardWidth = 280;   // 每個卡片寬度
            const cardHeight = 90;   // 每個卡片高度
            const spacing = 20;      // 卡片間距
            const coverSize = 70;    // 封面大小
            
            // 計算起始X位置以置中整組卡片
            const totalWidth = selectedSongs.length * cardWidth + (selectedSongs.length - 1) * spacing;
            let startX = (1080 - totalWidth) / 2;
            
            // 使用 Promise.all 確保所有圖片載入完成
            const drawPromises = selectedSongs.map(async (song, i) => {
                const cardX = startX + i * (cardWidth + spacing);
                const cardY = yPos;
                
                const title = currentLanguage === 'en' && song.titleEn ? song.titleEn : song.title;
                const artist = currentLanguage === 'en' && song.artistEn ? song.artistEn : song.artist;
                const album = song.album;
                
                // 繪製卡片背景
                ctx.fillStyle = '#f8f9fa';
                ctx.fillRect(cardX, cardY, cardWidth, cardHeight);
                
                // 繪製封面（方形，左側）
                const coverX = cardX + 10;
                const coverY = cardY + 10;
                
                await drawSquareImage(ctx, song.imageUrl, coverX, coverY, coverSize);
                
                // 繪製文字區域（封面右側，垂直置中）
                const textX = coverX + coverSize + 12;

                ctx.textAlign = 'left';

                // 先計算歌名會有幾行
                ctx.font = 'bold 18px "Source Sans 3", sans-serif';
                const maxWidth = cardWidth - coverSize - 35;
                const titleLines = wrapText(ctx, title, maxWidth, 2);

                // 計算實際的總行數和總高度
                const lineHeight = 20;
                const albumLines = 1;
                const songLines = titleLines.length;
                const artistLines = artist ? 1 : 0;
                const totalLines = albumLines + songLines + artistLines;
                const totalTextHeight = totalLines * lineHeight;

                // 計算起始Y位置（垂直置中）
                let currentY = cardY + (cardHeight - totalTextHeight) / 2 + 16;

                // 專輯名稱
                ctx.fillStyle = '#999999';
                ctx.font = '16px "Source Sans 3", sans-serif';
                ctx.fillText(`${album}`, textX, currentY);
                currentY += lineHeight;

                // 歌名（可能多行）
                ctx.fillStyle = '#333333';
                ctx.font = 'bold 18px "Source Sans 3", sans-serif';
                titleLines.forEach((line) => {
                    ctx.fillText(line, textX, currentY);
                    currentY += lineHeight;
                });

                // 演唱者
                if (artist) {
                    ctx.fillStyle = '#666666';
                    ctx.font = '16px "Source Sans 3", sans-serif';
                    const truncatedArtist = truncateText(ctx, artist, maxWidth);
                    ctx.fillText(truncatedArtist, textX, currentY);
                }
            });

            await Promise.all(drawPromises);
            
            yPos += cardHeight + 50;
        }
        
        // Performances section
        if (selectedPerformances.length > 0) {
            ctx.fillStyle = '#E0FFFF';
            drawRoundedRect(ctx, 80, yPos, 920, 50, 25);
            ctx.fillStyle = '#555555';
            ctx.font = 'bold 32px "Source Sans 3", sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText("🎭 我看了", 540, yPos + 35);
            
            yPos += 80;
            
            // Total performances
            ctx.font = 'bold 100px "Source Sans 3", sans-serif';
            ctx.fillStyle = '#333333';
            ctx.fillText(selectedPerformances.length.toString(), 540, yPos + 70);
            ctx.font = '28px "Source Sans 3", sans-serif';
            ctx.fillText('場演出', 540, yPos + 110);
            
            yPos += 170;
            
            // City distribution pie chart
            const cityData = aggregateByCity();
            if (Object.keys(cityData).length > 0) {
                ctx.fillStyle = '#F0FFF0';
                drawRoundedRect(ctx, 80, yPos, 920, 50, 25);
                ctx.fillStyle = '#555555';
                ctx.font = 'bold 32px "Source Sans 3", sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('🏙️ 城市分布', 540, yPos + 35);
                
                yPos += 70;
                await drawPieChart(cityData, 540, yPos + 100, 90, 'city');
                yPos += 240;
            }
            
            // Type distribution pie chart
            const typeData = aggregateByType();
            if (Object.keys(typeData).length > 0) {
                ctx.fillStyle = '#FFF8DC';
                drawRoundedRect(ctx, 80, yPos, 920, 50, 25);
                ctx.fillStyle = '#555555';
                ctx.font = 'bold 32px "Source Sans 3", sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('🎪 類型分布', 540, yPos + 35);
                
                yPos += 70;
                await drawPieChart(typeData, 540, yPos + 100, 90, 'type');
                yPos += 240;
            }
            
            // Monthly stacked bar chart
            yPos += 20;
            ctx.fillStyle = '#E6E6FA';
            drawRoundedRect(ctx, 80, yPos, 920, 50, 25);
            ctx.fillStyle = '#555555';
            ctx.font = 'bold 32px "Source Sans 3", sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('📊 每月觀看演出統計', 540, yPos + 35);
            
            yPos += 100;
            await drawStackedBarChart(yPos);
        } else if (userMessage) {
            // 沒有選演出，但有填訊息：顯示訊息
            ctx.fillStyle = '#FFF0F5';
            drawRoundedRect(ctx, 80, yPos, 920, 50, 25);
            ctx.fillStyle = '#555555';
            ctx.font = 'bold 32px "Source Sans 3", sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('💬 給 163braces 的話', 540, yPos + 35);
            
            yPos += 80;
            
            // 繪製訊息框
            ctx.fillStyle = '#ffffff';
            ctx.strokeStyle = '#e0e0e0';
            ctx.lineWidth = 2;
            const messageBoxHeight = 200;
            drawRoundedRect(ctx, 100, yPos, 880, messageBoxHeight, 15);
            ctx.stroke();
            
            // 繪製訊息文字（支援換行）
            ctx.fillStyle = '#333333';
            ctx.font = '24px "Source Sans 3", sans-serif';
            ctx.textAlign = 'center';
            
            // 使用 wrapText 函數處理換行
            const messageLines = wrapText(ctx, userMessage, 840, 6);
            const lineHeight = 32;
            const startY = yPos + (messageBoxHeight - (messageLines.length * lineHeight)) / 2 + 20;
            
            messageLines.forEach((line, index) => {
                ctx.fillText(line, 540, startY + (index * lineHeight));
            });
            
            yPos += messageBoxHeight + 30;
        }
        
        // Footer
        const footerY = Math.min(yPos + 350, 1850);  // 至少在 yPos+50，最多在 1850
        ctx.fillStyle = '#333333';
        ctx.font = '22px "Source Sans 3", sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Generated at 163braces.info/replay', 540, footerY);
    }
    
    function aggregateByCity() {
        const cityCount = {};
        selectedPerformances.forEach(p => {
            const city = currentLanguage === 'en' && p.cityEn ? p.cityEn : p.city;
            cityCount[city] = (cityCount[city] || 0) + 1;
        });
        
        // 降冪排序
        return Object.fromEntries(
            Object.entries(cityCount).sort((a, b) => b[1] - a[1])
        );
    }
    
    function aggregateByType() {
        const typeCount = {};
        selectedPerformances.forEach(p => {
            const type = currentLanguage === 'en' && p.typeEn ? p.typeEn : p.type;
            typeCount[type] = (typeCount[type] || 0) + 1;
        });
        
        // 降冪排序
        return Object.fromEntries(
            Object.entries(typeCount).sort((a, b) => b[1] - a[1])
        );
    }
    
    function drawPieChart(data, centerX, centerY, radius, dataType = 'city') {
        const colors = [ '#87CEEB', '#FFB347', '#FF7F7F', '#FFE55C', '#90EE90', '#DDA0DD',
                '#FFB6C1', '#E0E0E0', '#FFEFD5', '#F0E68C', '#E6E6FA', '#FDF5E6',
                '#F5DEB3', '#D3D3D3', '#FFE4E1', '#F0F8FF', '#FAF0E6', '#E0FFFF',
                '#FFF8DC', '#F5F5DC', '#FFFACD', '#F0FFF0', '#FFF0F5'];
        const typeColors = {};
    
        if (dataType === 'type') {
            // 類型分布：根據 order 分配顏色
            const typeOrderMap = {};
            selectedPerformances.forEach(p => {
                const type = currentLanguage === 'en' && p.typeEn ? p.typeEn : p.type;
                if (!(type in typeOrderMap)) {
                    typeOrderMap[type] = p.typeOrder;
                }
            });
            
            Object.keys(data).forEach(type => {
                const order = typeOrderMap[type] || 0;
                typeColors[type] = colors[(order - 1) % colors.length];
            });
        } else {
            // 城市分布：也根據 order 分配顏色
            const cityOrderMap = {};
            selectedPerformances.forEach(p => {
                const city = currentLanguage === 'en' && p.cityEn ? p.cityEn : p.city;
                if (!(city in cityOrderMap)) {
                    cityOrderMap[city] = p.cityOrder;
                }
            });
            
            Object.keys(data).forEach(city => {
                const order = cityOrderMap[city] || 0;
                typeColors[city] = colors[(order - 1) % colors.length];
            });
        }
        
        const total = Object.values(data).reduce((a, b) => a + b, 0);
        const entries = Object.entries(data); // 已經是降冪排序
        
        // Position pie chart on left side
        const pieX = 300;
        
        let startAngle = -Math.PI / 2;
        
        // Draw pie chart
        entries.forEach(([label, value]) => {
            const sliceAngle = (value / total) * 2 * Math.PI;
            
            ctx.fillStyle = typeColors[label] || '#cccccc';
            ctx.beginPath();
            ctx.moveTo(pieX, centerY);
            ctx.arc(pieX, centerY, radius, startAngle, startAngle + sliceAngle);
            ctx.closePath();
            ctx.fill();
            
            startAngle += sliceAngle;
        });
        
        // Draw legend with multi-column support
        const legendStartX = pieX + radius + 60;
        const legendItemHeight = 30;
        const legendColumnWidth = 140;
        const maxRows = 6;
        
        let legendX = legendStartX;
        let legendY = centerY - (Math.min(entries.length, maxRows) * legendItemHeight) / 2;
        
        ctx.font = '18px "Source Sans 3", sans-serif';
        ctx.textAlign = 'left';
        
        entries.forEach(([label, value], index) => {
            if (index > 0 && index % maxRows === 0) {
                legendX += legendColumnWidth;
                legendY = centerY - (Math.min(entries.length - index, maxRows) * legendItemHeight) / 2;
            }
            
            ctx.fillStyle = typeColors[label] || '#cccccc';
            ctx.fillRect(legendX, legendY, 20, 20);
            
            ctx.fillStyle = '#333333';
            ctx.fillText(`${label}: ${value}`, legendX + 28, legendY + 15);
            
            legendY += legendItemHeight;
        });
    }
    
    function drawStackedBarChart(startY) {
        const monthlyData = getMonthlyData();
        const chartHeight = 240;
        const barWidth = 55;
        
        // Calculate total chart width and center it
        const totalChartWidth = 12 * 73;
        const startX = (1080 - totalChartWidth) / 2;
        
        // 建立 type 到 order 的映射
        const typeOrderMap = {};
        selectedPerformances.forEach(p => {
            const type = currentLanguage === 'en' && p.typeEn ? p.typeEn : p.type;
            if (!(type in typeOrderMap)) {
                typeOrderMap[type] = p.typeOrder;
            }
        });
        
        // 按 order 排序的 uniqueTypes
        const uniqueTypes = [...new Set(selectedPerformances.map(p => 
            currentLanguage === 'en' && p.typeEn ? p.typeEn : p.type
        ))].sort((a, b) => typeOrderMap[a] - typeOrderMap[b]);
        
        // 根據 order 分配顏色
        const typeColors = {};
        const colors = ['#87CEEB', '#FFB347', '#FF7F7F', '#FFE55C', '#90EE90', '#DDA0DD',
                '#FFB6C1', '#E0E0E0', '#FFEFD5', '#F0E68C', '#E6E6FA', '#FDF5E6',
                '#F5DEB3', '#D3D3D3', '#FFE4E1', '#F0F8FF', '#FAF0E6', '#E0FFFF',
                '#FFF8DC', '#F5F5DC', '#FFFACD', '#F0FFF0', '#FFF0F5'];
        
        uniqueTypes.forEach(type => {
            const order = typeOrderMap[type];
            typeColors[type] = colors[(order - 1) % colors.length]; // order=1 對應 colors[0]
        });
        
        const maxValue = Math.max(...Object.values(monthlyData).map(m => 
            Object.values(m).reduce((a, b) => a + b, 0)
        ), 1);
        
        const scale = chartHeight / maxValue;
        
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        months.forEach((month, i) => {
            const monthData = monthlyData[i + 1] || {};
            const x = startX + i * 73;
            let y = startY + chartHeight;
            
            // 按 order 順序繪製（從小到大，所以 order=1 在最底部）
            uniqueTypes.forEach(type => {
                const count = monthData[type] || 0;
                if (count > 0) {
                    const barHeight = count * scale;
                    ctx.fillStyle = typeColors[type];
                    ctx.fillRect(x, y - barHeight, barWidth, barHeight);
                    y -= barHeight;
                }
            });

            // 計算該月總數
            const monthTotal = Object.values(monthData).reduce((sum, count) => sum + count, 0);

            // 如果該月有演出，在長條圖上方顯示總數
            if (monthTotal > 0) {
                ctx.fillStyle = '#666666';
                ctx.font = 'bold 22px "Source Sans 3", sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(monthTotal.toString(), x + barWidth / 2, y - 15);
            }
            
            ctx.fillStyle = '#333333';
            ctx.font = '18px "Source Sans 3", sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(month, x + barWidth / 2, startY + chartHeight + 25);
        });
        
        // Legend - 按 order 順序從左到右
        const legendEntries = uniqueTypes.map(type => [type, typeColors[type]]);
        const legendItemWidth = 140;
        const legendTotalWidth = Math.min(legendEntries.length * legendItemWidth, 600);
        let legendX = (1080 - legendTotalWidth) / 2;
        let legendY = startY + chartHeight + 50;
        
        ctx.font = '18px "Source Sans 3", sans-serif';
        ctx.textAlign = 'left';
        
        legendEntries.forEach(([type, color]) => {
            ctx.fillStyle = color;
            ctx.fillRect(legendX, legendY, 20, 20);
            
            ctx.fillStyle = '#333333';
            ctx.fillText(type, legendX + 28, legendY + 15);
            
            legendX += legendItemWidth;
            if (legendX > 540 + legendTotalWidth / 2) {
                legendX = (1080 - legendTotalWidth) / 2;
                legendY += 30;
            }
        });
    }
    
    function getMonthlyData() {
        const monthly = {};
        
        selectedPerformances.forEach(p => {
            const date = new Date(p.date);
            const month = date.getMonth() + 1;
            const type = currentLanguage === 'en' && p.typeEn ? p.typeEn : p.type;
            
            if (!monthly[month]) {
                monthly[month] = {};
            }
            
            monthly[month][type] = (monthly[month][type] || 0) + 1;
        });
        
        return monthly;
    }

    async function drawCircularImage(ctx, url, centerX, centerY, radius) {
        return new Promise(resolve => {
            const img = new Image();
            img.crossOrigin = 'Anonymous'; 
            img.onload = () => {
                ctx.save();
                
                // 剪裁路徑：圓形
                ctx.beginPath();
                ctx.arc(centerX, centerY, radius, 0, Math.PI * 2, true);
                ctx.closePath();
                ctx.clip();

                // 繪製圖片 (填滿圓形區域)
                const size = radius * 2;
                const x = centerX - radius;
                const y = centerY - radius;
                ctx.drawImage(img, x, y, size, size);

                // 繪製白色邊框 (可選)
                ctx.strokeStyle = 'white';
                ctx.lineWidth = 8;
                ctx.stroke();
                
                ctx.restore();
                resolve();
            };
            img.onerror = () => {
                console.error("Failed to load image:", url);
                // 圖片載入失敗時，畫一個圓形作為預留位置
                ctx.save();
                ctx.beginPath();
                ctx.arc(centerX, centerY, radius, 0, Math.PI * 2, true);
                ctx.closePath();
                ctx.fillStyle = '#cccccc'; 
                ctx.fill();
                ctx.font = '24px "Source Sans 3", sans-serif';
                ctx.fillStyle = '#666666';
                ctx.textAlign = 'center';
                ctx.fillText('No Cover', centerX, centerY + 8);
                ctx.restore();
                resolve();
            };
            img.src = url;
        });
    }
    async function drawSquareImage(ctx, url, x, y, size) {
        return new Promise(resolve => {
            const img = new Image();
            img.crossOrigin = 'Anonymous';
            img.onload = () => {
                ctx.save();
                
                // 繪製圓角矩形
                const radius = 6;
                ctx.beginPath();
                ctx.moveTo(x + radius, y);
                ctx.lineTo(x + size - radius, y);
                ctx.quadraticCurveTo(x + size, y, x + size, y + radius);
                ctx.lineTo(x + size, y + size - radius);
                ctx.quadraticCurveTo(x + size, y + size, x + size - radius, y + size);
                ctx.lineTo(x + radius, y + size);
                ctx.quadraticCurveTo(x, y + size, x, y + size - radius);
                ctx.lineTo(x, y + radius);
                ctx.quadraticCurveTo(x, y, x + radius, y);
                ctx.closePath();
                ctx.clip();
                
                // 繪製圖片
                ctx.drawImage(img, x, y, size, size);
                
                ctx.restore();
                resolve();
            };
            img.onerror = () => {
                console.error("Failed to load image:", url);
                // 圖片載入失敗時，畫一個灰色方框
                ctx.fillStyle = '#e0e0e0';
                ctx.fillRect(x, y, size, size);
                ctx.fillStyle = '#999999';
                ctx.font = '12px "Source Sans 3", sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('No Cover', x + size / 2, y + size / 2);
                resolve();
            };
            img.src = url;
        });
    }

    function truncateText(ctx, text, maxWidth) {
        if (ctx.measureText(text).width <= maxWidth) {
            return text;
        }
        
        let truncated = text;
        while (ctx.measureText(truncated + '...').width > maxWidth && truncated.length > 0) {
            truncated = truncated.slice(0, -1);
        }
        return truncated + '...';
    }

    function drawRoundedRect(ctx, x, y, width, height, radius) {
        ctx.beginPath();
        ctx.moveTo(x + radius, y);
        ctx.lineTo(x + width - radius, y);
        ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
        ctx.lineTo(x + width, y + height - radius);
        ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
        ctx.lineTo(x + radius, y + height);
        ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
        ctx.lineTo(x, y + radius);
        ctx.quadraticCurveTo(x, y, x + radius, y);
        ctx.closePath();
        ctx.fill();
    }

    async function drawLogo(ctx, url, x, y, maxWidth) {
        return new Promise(resolve => {
            const img = new Image();
            img.crossOrigin = 'Anonymous';
            img.onload = () => {
                // 計算縮放比例，保持寬高比
                const aspectRatio = img.height / img.width;
                const width = maxWidth;
                const height = width * aspectRatio;
                
                // 繪製 logo
                ctx.drawImage(img, x, y, width, height);
                resolve();
            };
            img.onerror = () => {
                console.error("Failed to load logo:", url);
                resolve();
            };
            img.src = url;
        });
    }

    function wrapText(ctx, text, maxWidth, maxLines = 2) {
        const words = text.split('');
        const lines = [];
        let currentLine = '';
        
        for (let i = 0; i < words.length; i++) {
            const testLine = currentLine + words[i];
            const metrics = ctx.measureText(testLine);
            
            if (metrics.width > maxWidth && currentLine.length > 0) {
                lines.push(currentLine);
                currentLine = words[i];
                
                if (lines.length >= maxLines - 1) {
                    // 已經達到最大行數，剩下的加 ...
                    const remaining = words.slice(i + 1).join('');
                    let lastLine = currentLine + remaining;
                    
                    while (ctx.measureText(lastLine + '...').width > maxWidth && lastLine.length > 0) {
                        lastLine = lastLine.slice(0, -1);
                    }
                    lines.push(lastLine + (lastLine.length < currentLine.length + remaining.length ? '...' : ''));
                    break;
                }
            } else {
                currentLine = testLine;
            }
        }
        
        if (lines.length < maxLines && currentLine) {
            lines.push(currentLine);
        }
        
        return lines;
    }

    const yearSelect = document.getElementById('year-select');
    if (yearSelect) yearSelect.addEventListener('change', changeYear);
})();
