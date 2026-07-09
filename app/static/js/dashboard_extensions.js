/* CalltoConvey Premium Dashboard Extensions Javascript */

// --- 0. Tab Session ID (tid) Propagation ---
(function() {
    const urlParams = new URLSearchParams(window.location.search);
    const tid = urlParams.get('tid');
    if (tid) {
        // Intercept all document clicks on links
        document.addEventListener('click', function(e) {
            const link = e.target.closest('a');
            if (link && link.href) {
                // Ensure it's an internal link and not a javascript link or anchor
                if (link.href.startsWith(window.location.origin) && !link.href.includes('#') && !link.href.startsWith('javascript:')) {
                    try {
                        const url = new URL(link.href);
                        if (!url.searchParams.has('tid')) {
                            url.searchParams.set('tid', tid);
                        }
                        
                        // Check if the click is meant to open in a new tab/window
                        const isNewTab = link.target === '_blank' || e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1;
                        if (!isNewTab) {
                            e.preventDefault();
                            window.location.href = url.toString();
                        } else {
                            link.href = url.toString();
                        }
                    } catch (err) {
                        console.error('Error rewriting link href:', err);
                    }
                }
            }
        });

        // Intercept inline onclick window.location.href redirections
        document.addEventListener('click', function(e) {
            let current = e.target;
            while (current && current !== document) {
                const onclickStr = current.getAttribute ? current.getAttribute('onclick') : null;
                if (onclickStr && onclickStr.includes('window.location.href')) {
                    const match = onclickStr.match(/window\.location\.href\s*=\s*(['"`])([^'"`\s\+]+)\1/);
                    if (match) {
                        e.preventDefault();
                        e.stopPropagation();
                        let urlStr = match[2];
                        try {
                            const url = new URL(urlStr, window.location.origin);
                            if (!url.searchParams.has('tid')) {
                                url.searchParams.set('tid', tid);
                            }
                            window.location.href = url.toString();
                        } catch (err) {
                            if (!urlStr.includes('tid=')) {
                                const separator = urlStr.includes('?') ? '&' : '?';
                                window.location.href = urlStr + separator + 'tid=' + tid;
                            } else {
                                window.location.href = urlStr;
                            }
                        }
                        return;
                    }
                }
                current = current.parentNode;
            }
        }, true); // Capture phase

        // Intercept form submissions
        document.addEventListener('submit', function(e) {
            const form = e.target;
            // Append tid to form action if it's internal
            if (form.action && form.action.startsWith(window.location.origin)) {
                try {
                    const url = new URL(form.action);
                    if (!url.searchParams.has('tid')) {
                        url.searchParams.set('tid', tid);
                        form.action = url.toString();
                    }
                } catch (err) {
                    console.error('Error rewriting form action:', err);
                }
            }
            
            // Also append tid as a hidden input element to ensure it's sent in POST body
            if (!form.querySelector('input[name="tid"]')) {
                const hiddenInput = document.createElement('input');
                hiddenInput.type = 'hidden';
                hiddenInput.name = 'tid';
                hiddenInput.value = tid;
                form.appendChild(hiddenInput);
            }
        });
    }
})();

document.addEventListener('DOMContentLoaded', function() {
    // --- 1. Global Setup & State ---
    const currentUserId = document.body.dataset.userId || '';
    const currentUserRole = document.body.dataset.userRole || '';
    let activeChatContactId = null;
    let activeChatContactRole = null;
    let chatPollInterval = null;
    let notificationPollInterval = null;
    let isEditingMessage = false;

    // Helper: CSRF protection token lookup
    function getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    // --- 2. Dynamic Scoped Search Autocomplete ---
    const searchInput = document.querySelector('.search-box input');
    const searchBox = document.querySelector('.search-box');
    if (searchInput && searchBox) {
        // Create dropdown element
        const dropdown = document.createElement('div');
        dropdown.className = 'search-autocomplete-dropdown';
        searchBox.appendChild(dropdown);

        searchInput.addEventListener('input', debounce(function() {
            const query = searchInput.value.trim();
            if (query.length < 2) {
                dropdown.innerHTML = '';
                dropdown.classList.remove('active');
                return;
            }

            fetch(`/api/search?q=${encodeURIComponent(query)}`)
                .then(res => res.json())
                .then(data => {
                    dropdown.innerHTML = '';
                    if (data.results.length === 0) {
                        dropdown.innerHTML = '<div class="search-no-results">No results found</div>';
                        dropdown.classList.add('active');
                        return;
                    }

                    // Group results by category
                    const grouped = {};
                    data.results.forEach(item => {
                        if (!grouped[item.category]) grouped[item.category] = [];
                        grouped[item.category].push(item);
                    });

                    for (const category in grouped) {
                        const catHeader = document.createElement('div');
                        catHeader.className = 'search-category-header';
                        catHeader.textContent = category;
                        dropdown.appendChild(catHeader);

                        grouped[category].forEach(item => {
                            const link = document.createElement('a');
                            link.href = item.link;
                            link.className = 'search-item-link';
                            link.innerHTML = `
                                <span class="search-item-title">${item.title}</span>
                                <span class="search-item-subtitle">${item.subtitle}</span>
                            `;
                            dropdown.appendChild(link);
                        });
                    }
                    dropdown.classList.add('active');
                })
                .catch(err => console.error('Search error:', err));
        }, 300));

        // Close dropdown on click outside
        document.addEventListener('click', function(e) {
            if (!searchBox.contains(e.target)) {
                dropdown.classList.remove('active');
            }
        });
    }

    // --- 3. Dynamic Notification Center ---
    const bellBtn = document.querySelector('.topbar-actions button .bi-bell')?.parentElement;
    const topbarActions = document.querySelector('.topbar-actions');
    if (bellBtn && topbarActions) {
        // Ensure badge exists
        let badge = bellBtn.querySelector('.notification-badge');
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'notification-badge';
            badge.style.cssText = 'position: absolute; top: -2px; right: -2px; background: #ef4444; color: white; border-radius: 50%; font-size: 0.65rem; width: 16px; height: 16px; display: flex; align-items: center; justify-content: center; font-weight: 700; border: 2px solid var(--glass-bg);';
            bellBtn.appendChild(badge);
        }

        // Create popover
        const popover = document.createElement('div');
        popover.className = 'notification-popover';
        popover.innerHTML = `
            <div class="notification-popover-header">
                <h6>Notifications</h6>
                <button class="notification-mark-all-btn">Mark all as read</button>
            </div>
            <div class="notification-popover-list">
                <div class="notification-popover-empty">No new notifications</div>
            </div>
        `;
        topbarActions.appendChild(popover);

        bellBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            popover.classList.toggle('active');
            // Close other popovers
            const chatDrawer = document.querySelector('.support-chat-drawer');
            if (chatDrawer) chatDrawer.classList.remove('active');
        });

        // Close popover on click outside
        document.addEventListener('click', function(e) {
            if (!popover.contains(e.target) && !bellBtn.contains(e.target)) {
                popover.classList.remove('active');
            }
        });

        // Fetch notifications
        function fetchNotifications() {
            fetch('/api/notifications')
                .then(res => res.json())
                .then(data => {
                    const listContainer = popover.querySelector('.notification-popover-list');
                    listContainer.innerHTML = '';

                    // Update badge
                    if (data.unread_count > 0) {
                        badge.textContent = data.unread_count;
                        badge.style.display = 'flex';
                    } else {
                        badge.style.display = 'none';
                    }

                    if (data.notifications.length === 0) {
                        listContainer.innerHTML = '<div class="notification-popover-empty">No new notifications</div>';
                        return;
                    }

                    data.notifications.forEach(n => {
                        const item = document.createElement('a');
                        item.href = n.link || '#';
                        item.className = `notification-popover-item ${n.is_read ? '' : 'unread'}`;
                        
                        let iconClass = 'bi-bell-fill';
                        let iconColor = 'var(--accent-purple)';
                        if (n.type === 'chat') {
                            iconClass = 'bi-chat-left-text-fill';
                            iconColor = 'var(--accent-pink)';
                        } else if (n.type === 'campaign') {
                            iconClass = 'bi-megaphone-fill';
                            iconColor = 'var(--accent-green)';
                        }

                        item.innerHTML = `
                            <div class="notification-popover-icon" style="color: ${iconColor};">
                                <i class="bi ${iconClass}"></i>
                            </div>
                            <div class="notification-popover-info">
                                <h6 class="notification-popover-title">${n.title}</h6>
                                <p class="notification-popover-desc">${n.message}</p>
                                <span class="notification-popover-time">${formatTime(n.created_at)}</span>
                            </div>
                        `;

                        // Mark as read on click
                        item.addEventListener('click', function(e) {
                            if (!n.is_read) {
                                fetch('/api/notifications/read', {
                                    method: 'POST',
                                    headers: {
                                        'Content-Type': 'application/json',
                                        'X-CSRFToken': getCsrfToken()
                                    },
                                    body: JSON.stringify({ id: n.id })
                                }).then(() => fetchNotifications());
                            }
                        });

                        listContainer.appendChild(item);
                    });
                })
                .catch(err => console.error('Error fetching notifications:', err));
        }

        // Mark all read action
        popover.querySelector('.notification-mark-all-btn').addEventListener('click', function(e) {
            e.stopPropagation();
            fetch('/api/notifications/read', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                }
            })
            .then(res => res.json())
            .then(() => fetchNotifications())
            .catch(err => console.error('Mark all read error:', err));
        });

        // First load and poll
        fetchNotifications();
        notificationPollInterval = setInterval(fetchNotifications, 10000);
    }

    // --- 4. Sliding Support Chat Drawer ---
    const chatBtn = document.querySelector('.topbar-actions button .bi-chat-left-dots')?.parentElement;
    if (chatBtn) {
        // Create the Drawer DOM structure and append to body
        const chatDrawer = document.createElement('div');
        chatDrawer.className = 'support-chat-drawer';
        chatDrawer.innerHTML = `
            <div class="chat-drawer-header">
                <h5><i class="bi bi-chat-square-text-fill"></i> Message Center</h5>
                <button class="chat-drawer-close-btn"><i class="bi bi-x-lg"></i></button>
            </div>
            <div class="chat-drawer-body">
                <!-- Contact List View -->
                <div class="chat-contacts-view">
                    <p style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-secondary); font-weight: 700; margin-bottom: 0.75rem;">Support Threads</p>
                    <div class="chat-contacts-list"></div>
                </div>

                <!-- Chat Thread View -->
                <div class="chat-thread-view">
                    <div class="chat-thread-header">
                        <button class="chat-back-btn"><i class="bi bi-chevron-left"></i></button>
                        <div class="contact-avatar" id="active-chat-avatar">S</div>
                        <div class="contact-info">
                            <h6 class="contact-name" id="active-chat-name">Active Conversation</h6>
                            <p class="contact-subtitle" id="active-chat-role">Platform Support</p>
                        </div>
                    </div>
                    <div class="chat-messages-container"></div>
                    <div class="chat-input-bar">
                        <input type="text" placeholder="Type a message...">
                        <button class="chat-send-btn"><i class="bi bi-send-fill"></i></button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(chatDrawer);

        // Drawer toggle buttons
        chatBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            chatDrawer.classList.toggle('active');
            if (chatDrawer.classList.contains('active')) {
                loadChatContacts();
                const popover = document.querySelector('.notification-popover');
                if (popover) popover.classList.remove('active');
            } else {
                stopChatPolling();
            }
        });

        chatDrawer.querySelector('.chat-drawer-close-btn').addEventListener('click', function() {
            chatDrawer.classList.remove('active');
            stopChatPolling();
        });

        chatDrawer.querySelector('.chat-back-btn').addEventListener('click', function() {
            chatDrawer.querySelector('.chat-thread-view').style.display = 'none';
            chatDrawer.querySelector('.chat-contacts-view').style.display = 'block';
            stopChatPolling();
        });

        // Close on click outside
        document.addEventListener('click', function(e) {
            if (!chatDrawer.contains(e.target) && !chatBtn.contains(e.target)) {
                chatDrawer.classList.remove('active');
                stopChatPolling();
            }
        });

        // Contacts list loader
        function loadChatContacts() {
            fetch('/api/chat/contacts')
                .then(res => res.json())
                .then(data => {
                    const list = chatDrawer.querySelector('.chat-contacts-list');
                    list.innerHTML = '';

                    if (data.contacts.length === 0) {
                        list.innerHTML = '<div class="text-center text-muted py-4" style="font-size: 0.8rem;">No contacts available</div>';
                        return;
                    }

                    data.contacts.forEach(c => {
                        const item = document.createElement('div');
                        item.className = 'chat-contact-item';
                        item.innerHTML = `
                            <div class="contact-avatar">${c.avatar}</div>
                            <div class="contact-info">
                                <h6 class="contact-name">${c.name}</h6>
                                <p class="contact-subtitle">${c.subtitle}</p>
                            </div>
                        `;
                        item.addEventListener('click', function() {
                            openChatThread(c.id, c.name, c.role, c.avatar);
                        });
                        list.appendChild(item);
                    });
                })
                .catch(err => console.error('Contacts error:', err));
        }

        // Open chat thread
        function openChatThread(id, name, role, avatar) {
            activeChatContactId = id;
            activeChatContactRole = role;
            
            chatDrawer.querySelector('.chat-contacts-view').style.display = 'none';
            const threadView = chatDrawer.querySelector('.chat-thread-view');
            threadView.style.display = 'flex';

            threadView.querySelector('#active-chat-avatar').textContent = avatar;
            threadView.querySelector('#active-chat-name').textContent = name;
            threadView.querySelector('#active-chat-role').textContent = role === 'platform_admin' ? 'System Administrator' : role.replace('_', ' ').toUpperCase();

            fetchMessages();
            chatPollInterval = setInterval(fetchMessages, 4000);
        }

        // Helper to escape HTML to prevent XSS
        function escapeHtml(str) {
            if (!str) return '';
            return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
        }

        // Fetch active messages
        function fetchMessages() {
            if (activeChatContactId === null || activeChatContactRole === null || isEditingMessage) return;
            fetch(`/api/chat/messages?contact_id=${activeChatContactId}&contact_role=${activeChatContactRole}`)
                .then(res => res.json())
                .then(data => {
                    const container = chatDrawer.querySelector('.chat-messages-container');
                    const isAtBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 100;
                    container.innerHTML = '';

                    if (data.messages.length === 0) {
                        container.innerHTML = '<div class="text-center text-muted my-auto" style="font-size: 0.8rem; opacity: 0.6;">No messages yet.<br>Start the conversation!</div>';
                        return;
                    }

                    // Build user unique key to check my reactions
                    const myUserKey = `${currentUserRole === 'platform_owner' ? 'platform_admin' : currentUserRole}_${currentUserId}`;

                    data.messages.forEach(m => {
                        const isSent = (m.sender_type === 'platform_admin' && currentUserRole === 'platform_owner') || 
                                       (m.sender_type !== 'platform_admin' && m.sender_id.toString() === currentUserId);
                        
                        // Parse reactions counts
                        const reactionCounts = {};
                        let totalReactions = 0;
                        let myReactionEmoji = null;
                        
                        for (const userKey in m.reactions || {}) {
                            const emoji = m.reactions[userKey];
                            reactionCounts[emoji] = (reactionCounts[emoji] || 0) + 1;
                            totalReactions++;
                            if (userKey === myUserKey) {
                                myReactionEmoji = emoji;
                            }
                        }
                        
                        let reactionsHtml = '';
                        if (totalReactions > 0) {
                            reactionsHtml = `<div class="bubble-reactions-display" title="Click to remove your reaction">`;
                            for (const emoji in reactionCounts) {
                                reactionsHtml += `<span>${emoji}</span>`;
                            }
                            if (totalReactions > 1) {
                                reactionsHtml += `<span class="reaction-count">${totalReactions}</span>`;
                            }
                            reactionsHtml += `</div>`;
                        }

                        const wrapper = document.createElement('div');
                        wrapper.className = `chat-bubble-wrapper ${isSent ? 'sent' : 'received'}`;
                        wrapper.dataset.messageId = m.id;
                        
                        let bubbleInnerHtml = '';
                        if (m.is_deleted) {
                            bubbleInnerHtml = `
                                <div class="chat-bubble received deleted">
                                    <div class="deleted-text"><i class="bi bi-ban"></i> This message was deleted</div>
                                    <div class="chat-bubble-meta">
                                        <span class="chat-bubble-time">${formatTime(m.created_at)}</span>
                                    </div>
                                </div>
                            `;
                        } else {
                            bubbleInnerHtml = `
                                <div class="chat-bubble ${isSent ? 'sent' : 'received'}">
                                    <div class="message-content-text">${escapeHtml(m.message)}</div>
                                    <div class="chat-bubble-meta">
                                        ${m.is_edited ? '<span class="edited-badge">Edited</span>' : ''}
                                        <span class="chat-bubble-time">${formatTime(m.created_at)}</span>
                                    </div>
                                    ${reactionsHtml}
                                </div>
                                <div class="chat-bubble-actions">
                                    <div class="quick-emojis">
                                        <span class="emoji-btn" data-emoji="👍">👍</span>
                                        <span class="emoji-btn" data-emoji="❤️">❤️</span>
                                        <span class="emoji-btn" data-emoji="😂">😂</span>
                                        <span class="emoji-btn" data-emoji="😮">😮</span>
                                        <span class="emoji-btn" data-emoji="😢">😢</span>
                                        <span class="emoji-btn" data-emoji="🙏">🙏</span>
                                    </div>
                                    <button class="chat-action-menu-btn"><i class="bi bi-three-dots-vertical"></i></button>
                                    <div class="chat-bubble-menu">
                                        ${isSent ? `
                                            <button class="chat-menu-item edit-btn"><i class="bi bi-pencil-square"></i> Edit</button>
                                            <button class="chat-menu-item delete-btn text-danger"><i class="bi bi-trash"></i> Delete</button>
                                        ` : ''}
                                        <button class="chat-menu-item toggle-reaction-btn"><i class="bi bi-emoji-smile"></i> React</button>
                                    </div>
                                </div>
                            `;
                        }
                        
                        wrapper.innerHTML = bubbleInnerHtml;
                        
                        // Event Listeners for actions (only if not deleted)
                        if (!m.is_deleted) {
                            const menuBtn = wrapper.querySelector('.chat-action-menu-btn');
                            const menu = wrapper.querySelector('.chat-bubble-menu');
                            
                            // Toggle actions menu
                            if (menuBtn && menu) {
                                menuBtn.addEventListener('click', function(e) {
                                    e.stopPropagation();
                                    // Close any other open menus
                                    document.querySelectorAll('.chat-bubble-menu.active').forEach(m => {
                                        if (m !== menu) m.classList.remove('active');
                                    });
                                    menu.classList.toggle('active');
                                });
                            }
                            
                            // Quick emojis selection
                            wrapper.querySelectorAll('.quick-emojis .emoji-btn').forEach(btn => {
                                btn.addEventListener('click', function() {
                                    const emoji = btn.dataset.emoji;
                                    const newEmoji = (myReactionEmoji === emoji) ? null : emoji;
                                    sendReaction(m.id, newEmoji);
                                    if (menu) menu.classList.remove('active');
                                });
                            });
                            
                            // Toggle reaction btn inside dropdown
                            const toggleReactBtn = wrapper.querySelector('.toggle-reaction-btn');
                            if (toggleReactBtn) {
                                toggleReactBtn.addEventListener('click', function(e) {
                                    e.stopPropagation();
                                    const emojisBar = wrapper.querySelector('.quick-emojis');
                                    if (emojisBar) {
                                        emojisBar.style.transform = 'scale(1.1)';
                                        setTimeout(() => emojisBar.style.transform = 'scale(1)', 200);
                                    }
                                    if (menu) menu.classList.remove('active');
                                });
                            }
                            
                            // Delete button action
                            const deleteBtn = wrapper.querySelector('.delete-btn');
                            if (deleteBtn) {
                                deleteBtn.addEventListener('click', function() {
                                    if (confirm('Are you sure you want to delete this message?')) {
                                        deleteMessage(m.id);
                                    }
                                    if (menu) menu.classList.remove('active');
                                });
                            }
                            
                            // Edit button action
                            const editBtn = wrapper.querySelector('.edit-btn');
                            if (editBtn) {
                                editBtn.addEventListener('click', function() {
                                    if (menu) menu.classList.remove('active');
                                    isEditingMessage = true;
                                    
                                    const bubbleEl = wrapper.querySelector('.chat-bubble');
                                    const originalText = m.message;
                                    
                                    // Create inline editor
                                    bubbleEl.innerHTML = `
                                        <div class="chat-edit-container">
                                            <input type="text" class="chat-edit-input" value="${escapeHtml(originalText)}">
                                            <div class="chat-edit-actions">
                                                <button class="chat-edit-btn cancel">Cancel</button>
                                                <button class="chat-edit-btn save">Save</button>
                                            </div>
                                        </div>
                                    `;
                                    
                                    const input = bubbleEl.querySelector('.chat-edit-input');
                                    input.focus();
                                    input.select();
                                    
                                    // Handle cancel
                                    bubbleEl.querySelector('.chat-edit-btn.cancel').addEventListener('click', function(e) {
                                        e.stopPropagation();
                                        isEditingMessage = false;
                                        fetchMessages(); // reload message thread
                                    });
                                    
                                    // Handle save
                                    bubbleEl.querySelector('.chat-edit-btn.save').addEventListener('click', function(e) {
                                        e.stopPropagation();
                                        const newText = input.value.trim();
                                        if (newText && newText !== originalText) {
                                            isEditingMessage = false;
                                            editMessage(m.id, newText);
                                        } else {
                                            isEditingMessage = false;
                                            fetchMessages();
                                        }
                                    });
                                    
                                    // Handle Enter/Esc in input
                                    input.addEventListener('keydown', function(e) {
                                        if (e.key === 'Enter') {
                                            e.stopPropagation();
                                            const newText = input.value.trim();
                                            if (newText && newText !== originalText) {
                                                isEditingMessage = false;
                                                editMessage(m.id, newText);
                                            } else {
                                                isEditingMessage = false;
                                                fetchMessages();
                                            }
                                        } else if (e.key === 'Escape') {
                                            e.stopPropagation();
                                            isEditingMessage = false;
                                            fetchMessages();
                                        }
                                    });
                                });
                            }
                            
                            // Click reaction display to toggle off
                            const reactionDisplay = wrapper.querySelector('.bubble-reactions-display');
                            if (reactionDisplay && myReactionEmoji) {
                                reactionDisplay.addEventListener('click', function() {
                                    sendReaction(m.id, null); // remove reaction
                                });
                            }
                        }

                        container.appendChild(wrapper);
                    });

                    // Close any active menus when clicking anywhere in container
                    container.addEventListener('click', function() {
                        document.querySelectorAll('.chat-bubble-menu.active').forEach(m => m.classList.remove('active'));
                    });

                    // Scroll to bottom if user is close to bottom
                    if (isAtBottom) {
                        container.scrollTop = container.scrollHeight;
                    }
                })
                .catch(err => console.error('Messages error:', err));
        }

        // Send Emoji Reaction API
        function sendReaction(messageId, emoji) {
            fetch('/api/chat/react', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({ message_id: messageId, emoji: emoji })
            })
            .then(res => res.json())
            .then(() => fetchMessages())
            .catch(err => console.error('React error:', err));
        }

        // Delete Message API
        function deleteMessage(messageId) {
            fetch('/api/chat/delete', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({ message_id: messageId })
            })
            .then(res => res.json())
            .then(() => fetchMessages())
            .catch(err => console.error('Delete error:', err));
        }

        // Edit Message API
        function editMessage(messageId, newText) {
            fetch('/api/chat/edit', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({ message_id: messageId, message: newText })
            })
            .then(res => res.json())
            .then(() => fetchMessages())
            .catch(err => console.error('Edit error:', err));
        }

        // Send Message
        const chatInput = chatDrawer.querySelector('.chat-input-bar input');
        const sendBtn = chatDrawer.querySelector('.chat-send-btn');

        function sendMessage() {
            const text = chatInput.value.trim();
            if (!text || activeChatContactId === null) return;

            chatInput.value = '';
            
            fetch('/api/chat/send', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({
                    recipient_id: activeChatContactId,
                    recipient_role: activeChatContactRole,
                    message: text
                })
            })
            .then(res => res.json())
            .then(data => {
                fetchMessages();
            })
            .catch(err => console.error('Send error:', err));
        }

        sendBtn.addEventListener('click', sendMessage);
        chatInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') sendMessage();
        });

        function stopChatPolling() {
            if (chatPollInterval) {
                clearInterval(chatPollInterval);
                chatPollInterval = null;
            }
            activeChatContactId = null;
            activeChatContactRole = null;
        }
    }

    // --- 5. Floating AI Assistant Widget ---
    // Create AI floating widget HTML structures and append
    const aiWidget = document.createElement('div');
    aiWidget.innerHTML = `
        <div class="ai-assistant-trigger" title="Ask CalltoConvey Assistant">
            <i class="bi bi-robot"></i>
        </div>
        <div class="ai-chat-viewport">
            <div class="ai-chat-header">
                <h6><i class="bi bi-robot" style="color: var(--accent-purple);"></i> CalltoConvey AI Helper</h6>
                <button class="ai-chat-close-btn"><i class="bi bi-x-lg"></i></button>
            </div>
            <div class="ai-messages-container">
                <div class="ai-message bot">
                    <div class="ai-card">
                        <h5>👋 CalltoConvey Assistant</h5>
                        <p>Welcome! I'm your interactive platform guide. Ask me any question regarding your workspace functionalities, and I'll display custom guide paths instantly!</p>
                        <p style="font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0;">Try: <code>How to create a campaign?</code> or <code>How to manage workers?</code></p>
                    </div>
                </div>
            </div>
            <div class="chat-input-bar" style="border-top: 1px solid var(--glass-border);">
                <input type="text" placeholder="Ask AI how to...">
                <button class="chat-send-btn" style="background: linear-gradient(135deg, var(--accent-purple), var(--accent-pink));"><i class="bi bi-send-fill"></i></button>
            </div>
        </div>
    `;
    document.body.appendChild(aiWidget);

    const aiTrigger = aiWidget.querySelector('.ai-assistant-trigger');
    const aiViewport = aiWidget.querySelector('.ai-chat-viewport');
    const aiClose = aiWidget.querySelector('.ai-chat-close-btn');
    const aiInput = aiViewport.querySelector('.chat-input-bar input');
    const aiSend = aiViewport.querySelector('.chat-input-bar button');
    const aiMsgContainer = aiViewport.querySelector('.ai-messages-container');

    aiTrigger.addEventListener('click', function() {
        aiViewport.classList.toggle('active');
        if (aiViewport.classList.contains('active')) {
            aiInput.focus();
        }
    });

    aiClose.addEventListener('click', function() {
        aiViewport.classList.remove('active');
    });

    function askAI() {
        const q = aiInput.value.trim();
        if (!q) return;

        aiInput.value = '';

        // Append user bubble
        const userBubble = document.createElement('div');
        userBubble.className = 'ai-message user';
        userBubble.textContent = q;
        aiMsgContainer.appendChild(userBubble);
        aiMsgContainer.scrollTop = aiMsgContainer.scrollHeight;

        // Append typing indicator
        const typing = document.createElement('div');
        typing.className = 'ai-message bot typing-indicator-item';
        typing.innerHTML = `
            <div class="ai-typing-indicator">
                <span></span>
                <span></span>
                <span></span>
            </div>
        `;
        aiMsgContainer.appendChild(typing);
        aiMsgContainer.scrollTop = aiMsgContainer.scrollHeight;

        fetch('/api/ai-assistant/ask', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ question: q })
        })
        .then(res => res.json())
        .then(data => {
            // Remove typing indicator
            const oldTyping = aiMsgContainer.querySelector('.typing-indicator-item');
            if (oldTyping) oldTyping.remove();

            // Append bot bubble
            const botBubble = document.createElement('div');
            botBubble.className = 'ai-message bot';
            botBubble.innerHTML = data.answer;
            aiMsgContainer.appendChild(botBubble);
            aiMsgContainer.scrollTop = aiMsgContainer.scrollHeight;
        })
        .catch(err => {
            console.error('AI Assistant Error:', err);
            const oldTyping = aiMsgContainer.querySelector('.typing-indicator-item');
            if (oldTyping) oldTyping.remove();
        });
    }

    aiSend.addEventListener('click', askAI);
    aiInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') askAI();
    });

    // --- 6. First-Time Guided Onboarding Tour ---
    // Check if onboarding completed is FALSE (read from body data-attribute)
    const onboardingCompleted = document.body.dataset.onboardingCompleted === 'true';
    if (!onboardingCompleted && currentUserRole !== 'platform_owner') {
        runGuidedTour();
    }

    function runGuidedTour() {
        let steps = [];
        if (currentUserRole === 'org_admin') {
            steps = [
                {
                    title: "👋 CalltoConvey Admin Center",
                    desc: "Welcome to your Organization Admin Dashboard! Here, you have complete control over workforce agents, automated campaigns, customized CRM modules, and real-time support. Let's take a quick 1-minute guided tour.",
                    target: null
                },
                {
                    title: "👥 Workforce Management",
                    desc: "Register and monitor your support agents. Manage logins, configure active permissions, and view daily productivity metrics instantly here.",
                    target: "a[href*='workers']"
                },
                {
                    title: "📊 Central Command Dashboard",
                    desc: "Access your custom CRM workspace modules. Inspect active tickets, client contacts, and real-time operational data scoped to your enterprise.",
                    target: "a[href*='dashboard']"
                },
                {
                    title: "📣 Automated Campaigns",
                    desc: "Launch broadcasting marketing sequences. Configure template criteria, schedule broadcasts, and optimize response pipelines dynamically.",
                    target: "a[href*='campaigns']"
                },
                {
                    title: "💬 Admin Support Hotline",
                    desc: "Need assistance? Click this bubble to chat directly with our Platform System Support team, raising tickets and resolving audits in real-time.",
                    target: ".topbar-actions button .bi-chat-left-dots"
                },
                {
                    title: "🤖 Connected AI Copilot",
                    desc: "Confused about setup or analytics data? Launch the CalltoConvey AI Helper anytime from the corner to get step-by-step visuals and shortcut actions instantly!",
                    target: ".ai-assistant-trigger"
                }
            ];
        } else {
            // default or worker
            steps = [
                {
                    title: "👋 CalltoConvey Workforce Portal",
                    desc: "Welcome to your Worker Workspace! This hub is designed for workforce members to handle assigned CRM entries, review tickets, and coordinate daily tasks. Let's run a quick operational tour.",
                    target: null
                },
                {
                    title: "🔍 Scoped Workspace Search",
                    desc: "Quickly lookup customer care files, task guidelines, or CRM cards. Autocomplete highlights are completely scoped to your active permissions.",
                    target: ".search-box"
                },
                {
                    title: "📋 Operational Reports",
                    desc: "Submit and review daily operational logs, audit status sheets, and performance metrics to keep management updated seamlessly.",
                    target: "a[href*='reports']"
                },
                {
                    title: "💬 Team Communication Hotline",
                    desc: "Tap the topbar messaging control to open a direct support thread. Communicate instantly with your Organization Admin or system operators.",
                    target: ".topbar-actions button .bi-chat-left-dots"
                },
                {
                    title: "🤖 CalltoConvey AI Helper",
                    desc: "Whenever you need interactive guides or quick shortcut paths, tap the robot button to trigger the CalltoConvey AI Copilot immediately.",
                    target: ".ai-assistant-trigger"
                }
            ];
        }

        let currentStep = 0;

        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'guided-tour-overlay';
        document.body.appendChild(overlay);

        // Position helper
        function positionTourCard(card, targetEl) {
            // Remove previous classes
            card.classList.remove('arrow-top', 'arrow-bottom');

            if (!targetEl) {
                // Center the card in the viewport
                card.style.position = 'fixed';
                card.style.top = '50%';
                card.style.left = '50%';
                card.style.transform = 'translate(-50%, -50%)';
                return;
            }

            const rect = targetEl.getBoundingClientRect();
            card.style.position = 'fixed';
            card.style.transform = 'none';

            const cardWidth = card.offsetWidth || 440;
            const cardHeight = card.offsetHeight || 220;
            const gap = 16;

            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;

            // Preferred position: below the target element
            let top = rect.bottom + gap;
            let left = rect.left + (rect.width - cardWidth) / 2;
            let arrowClass = 'arrow-top';

            // Check if it fits below. If not, place above.
            if (top + cardHeight > viewportHeight - 12) {
                top = rect.top - cardHeight - gap;
                arrowClass = 'arrow-bottom';
            }

            // Adjustments
            if (left < 12) left = 12;
            if (left + cardWidth > viewportWidth - 12) left = viewportWidth - cardWidth - 12;
            if (top < 12) {
                // Fallback: center in viewport
                top = (viewportHeight - cardHeight) / 2;
                left = (viewportWidth - cardWidth) / 2;
                arrowClass = '';
            }

            card.style.top = `${top}px`;
            card.style.left = `${left}px`;
            if (arrowClass) {
                card.classList.add(arrowClass);
                // Align pointing arrow center
                const arrowOffset = (rect.left + rect.width / 2) - left;
                card.style.setProperty('--arrow-offset', `${Math.max(20, Math.min(cardWidth - 20, arrowOffset))}px`);
            }
        }

        let resizeHandler = null;

        function showStep(index) {
            // Remove previous highlights
            document.querySelectorAll('.tour-highlighted-element').forEach(el => {
                el.classList.remove('tour-highlighted-element');
            });

            const step = steps[index];

            // Re-render modal inside overlay
            overlay.innerHTML = `
                <div class="guided-tour-card">
                    <span class="tour-step-badge">STEP ${index + 1} OF ${steps.length}</span>
                    <h4 class="tour-title"><i class="bi bi-compass" style="color: #4b5563;"></i> ${step.title}</h4>
                    <p class="tour-desc">${step.desc}</p>
                    <div class="tour-footer">
                        <div class="tour-dots">
                            ${steps.map((_, i) => `<div class="tour-dot ${i === index ? 'active' : ''}"></div>`).join('')}
                        </div>
                        <div class="tour-actions-btn-group">
                            <button class="tour-skip-btn">Skip</button>
                            <button class="tour-next-btn">${index === steps.length - 1 ? 'Finish' : 'Next'}</button>
                        </div>
                    </div>
                </div>
            `;

            const card = overlay.querySelector('.guided-tour-card');

            // Highlight target if present
            let targetEl = null;
            if (step.target) {
                targetEl = document.querySelector(step.target);
                // Fallback selector variations
                if (!targetEl && step.target.includes('bi-chat-left-dots')) {
                    targetEl = document.querySelector('.topbar-actions button .bi-chat-left-dots')?.parentElement || document.querySelector('.topbar-actions');
                }
                
                if (targetEl) {
                    targetEl.classList.add('tour-highlighted-element');
                    targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }

            if (!targetEl) {
                overlay.classList.add('center-card');
            } else {
                overlay.classList.remove('center-card');
            }

            // Perform initial positioning
            setTimeout(() => {
                positionTourCard(card, targetEl);
            }, 100);

            // Clean up old resize listener
            if (resizeHandler) {
                window.removeEventListener('resize', resizeHandler);
            }

            // Bind new resize listener
            resizeHandler = function() {
                positionTourCard(card, targetEl);
            };
            window.addEventListener('resize', resizeHandler);

            // Click Handlers
            overlay.querySelector('.tour-skip-btn').addEventListener('click', endTour);
            overlay.querySelector('.tour-next-btn').addEventListener('click', function() {
                if (index < steps.length - 1) {
                    currentStep++;
                    showStep(currentStep);
                } else {
                    endTour();
                }
            });
        }

        function endTour() {
            // Clean up resize listener
            if (resizeHandler) {
                window.removeEventListener('resize', resizeHandler);
                resizeHandler = null;
            }

            // Remove highlighting
            document.querySelectorAll('.tour-highlighted-element').forEach(el => {
                el.classList.remove('tour-highlighted-element');
            });
            overlay.remove();

            // Notify backend that onboarding is completed
            fetch('/api/onboarding/complete', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                }
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    document.body.dataset.onboardingCompleted = 'true';
                }
            })
            .catch(err => console.error('Error saving onboarding complete:', err));
        }

        // Start Onboarding
        showStep(0);
    }

    // --- 7. Utility Helper Functions ---
    function debounce(func, wait) {
        let timeout;
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    function formatTime(isoString) {
        try {
            if (!isoString) return '';
            let formatString = isoString;
            // Treat naive ISO strings without timezone offsets as UTC
            if (!formatString.endsWith('Z') && !formatString.includes('+') && !formatString.match(/-\d{2}:\d{2}$/)) {
                formatString += 'Z';
            }
            const date = new Date(formatString);
            const now = new Date();
            const diffMs = now - date;
            const diffMins = Math.floor(diffMs / 60000);
            
            if (diffMins < 1) return 'Just now';
            if (diffMins < 60) return `${diffMins}m ago`;
            
            const diffHours = Math.floor(diffMins / 60);
            if (diffHours < 24) return `${diffHours}h ago`;
            
            return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
        } catch (e) {
            return '';
        }
    }

    // --- 8. Customer Care Floating Support Widget ---
    if (currentUserRole === 'org_admin' || currentUserRole === 'worker') {
        initSupportWidget();
    }

    function initSupportWidget() {
        // Create Trigger DOM
        const trigger = document.createElement('div');
        trigger.className = 'support-trigger';
        trigger.setAttribute('title', 'Customer Care Support');
        trigger.innerHTML = '<i class="bi bi-headset"></i>';
        
        // Create Viewport DOM
        const viewport = document.createElement('div');
        viewport.className = 'support-viewport';
        viewport.innerHTML = `
            <div class="support-header">
                <h5><i class="bi bi-headset"></i> Helpdesk Support</h5>
                <button class="close-btn"><i class="bi bi-x-lg"></i></button>
            </div>
            <div class="support-tabs">
                <button class="support-tab-btn active" data-tab="new-ticket">New Ticket</button>
                <button class="support-tab-btn" data-tab="history">Ticket History</button>
            </div>
            <div class="support-body">
                <div class="support-pane active" id="pane-new-ticket">
                    <div class="support-field">
                        <label for="support-message">Describe your issue or query:</label>
                        <textarea id="support-message" placeholder="Type your issue or query details here... We'll notify you as soon as it's resolved."></textarea>
                    </div>
                    <button class="support-submit-btn" id="support-submit-btn">
                        <i class="bi bi-send-fill"></i> Submit Query
                    </button>
                </div>
                <div class="support-pane" id="pane-history">
                    <div class="support-tickets-list">
                        <!-- Loaded dynamically -->
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(trigger);
        document.body.appendChild(viewport);
        
        const closeBtn = viewport.querySelector('.close-btn');
        const tabBtns = viewport.querySelectorAll('.support-tab-btn');
        const panes = viewport.querySelectorAll('.support-pane');
        const submitBtn = viewport.querySelector('#support-submit-btn');
        const messageArea = viewport.querySelector('#support-message');
        const ticketsList = viewport.querySelector('.support-tickets-list');
        
        let supportPollInterval = null;
        
        // Toggle Active
        trigger.addEventListener('click', function(e) {
            e.stopPropagation();
            viewport.classList.toggle('active');
            if (viewport.classList.contains('active')) {
                loadSupportHistory();
                startSupportPolling();
            } else {
                stopSupportPolling();
            }
        });

        // Wire additional sidebar & dashboard triggers
        const sidebarTrigger = document.getElementById('sidebar-support-trigger');
        if (sidebarTrigger) {
            sidebarTrigger.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                viewport.classList.add('active');
                loadSupportHistory();
                startSupportPolling();
            });
        }

        const dashboardBtn = document.getElementById('dashboard-support-btn');
        if (dashboardBtn) {
            dashboardBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                viewport.classList.add('active');
                loadSupportHistory();
                startSupportPolling();
            });
        }
        
        closeBtn.addEventListener('click', function() {
            viewport.classList.remove('active');
            stopSupportPolling();
        });
        
        // Close on click outside
        document.addEventListener('click', function(e) {
            if (!viewport.contains(e.target) && !trigger.contains(e.target)) {
                viewport.classList.remove('active');
                stopSupportPolling();
            }
        });
        
        // Tab switching
        tabBtns.forEach(btn => {
            btn.addEventListener('click', function() {
                tabBtns.forEach(b => b.classList.remove('active'));
                panes.forEach(p => p.classList.remove('active'));
                
                this.classList.add('active');
                const tabId = this.dataset.tab;
                viewport.querySelector(`#pane-${tabId}`).classList.add('active');
                
                if (tabId === 'history') {
                    loadSupportHistory();
                }
            });
        });
        
        // Submit Query Action
        submitBtn.addEventListener('click', function() {
            const message = messageArea.value.trim();
            if (!message) {
                alert('Please type a message before submitting.');
                return;
            }
            
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Submitting...';
            
            fetch('/api/helpdesk/create', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({ message: message })
            })
            .then(res => res.json())
            .then(data => {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="bi bi-send-fill"></i> Submit Query';
                
                if (data.success) {
                    messageArea.value = '';
                    
                    // Visual confirmation
                    alert(`Query submitted successfully! Your Ticket Number is: ${data.query.ticket_number}`);
                    
                    // Switch to history tab
                    tabBtns.forEach(b => {
                        if (b.dataset.tab === 'history') b.click();
                    });
                } else {
                    alert('Failed to submit query: ' + (data.error || 'Unknown error'));
                }
            })
            .catch(err => {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="bi bi-send-fill"></i> Submit Query';
                console.error('Error submitting support query:', err);
                alert('An error occurred. Please try again.');
            });
        });
        
        // Load Support History List
        function loadSupportHistory() {
            fetch('/api/helpdesk/list')
            .then(res => res.json())
            .then(data => {
                ticketsList.innerHTML = '';
                
                if (!data.queries || data.queries.length === 0) {
                    ticketsList.innerHTML = `
                        <div class="text-center text-muted py-5" style="font-size: 0.85rem;">
                            <i class="bi bi-headset" style="font-size: 2rem; display: block; margin-bottom: 0.5rem; color: #d1d5db;"></i>
                            No queries raised yet
                        </div>
                    `;
                    return;
                }
                
                data.queries.forEach(q => {
                    const card = document.createElement('div');
                    card.className = 'ticket-item-card';
                    
                    const isPending = q.status === 'Pending';
                    const statusClass = isPending ? 'pending' : 'resolved';
                    
                    let resolvedInfo = '';
                    if (q.resolved_at) {
                        resolvedInfo = `<span>Solved: ${formatTime(q.resolved_at)}</span>`;
                    }
                    
                    card.innerHTML = `
                        <div class="ticket-item-header">
                            <span class="ticket-item-id">${q.ticket_number}</span>
                            <span class="ticket-item-badge ${statusClass}">${q.status}</span>
                        </div>
                        <div class="ticket-item-message">${escapeHtml(q.message)}</div>
                        <div class="ticket-item-footer">
                            <span>Raised: ${formatTime(q.created_at)}</span>
                            ${resolvedInfo}
                        </div>
                    `;
                    ticketsList.appendChild(card);
                });
            })
            .catch(err => {
                console.error('Error loading support queries:', err);
                ticketsList.innerHTML = '<div class="text-center text-danger py-4" style="font-size: 0.8rem;">Failed to load ticket history</div>';
            });
        }
        
        function escapeHtml(str) {
            return str
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }
        
        function startSupportPolling() {
            stopSupportPolling();
            supportPollInterval = setInterval(loadSupportHistory, 10000);
        }
        
        function stopSupportPolling() {
            if (supportPollInterval) {
                clearInterval(supportPollInterval);
                supportPollInterval = null;
            }
        }

        // --- Breadcrumbs Generator ---
        (function() {
            const topbar = document.querySelector('.premium-topbar');
            if (!topbar) return;

            const path = window.location.pathname;
            const segments = path.split('/').filter(p => p);
            if (segments.length === 0) return;

            const urlParams = new URLSearchParams(window.location.search);
            const tid = urlParams.get('tid');
            const tidSuffix = tid ? `?tid=${tid}` : '';

            const breadcrumbNav = document.createElement('nav');
            breadcrumbNav.className = 'premium-breadcrumbs';
            breadcrumbNav.setAttribute('aria-label', 'breadcrumb');

            const list = document.createElement('ol');
            list.className = 'breadcrumb-list';

            // Base Root mapping based on portal prefix
            const portal = segments[0];
            let portalName = "Workspace";
            let portalUrl = "/worker/dashboard";

            if (portal === 'org') {
                portalName = "Org Admin";
                portalUrl = "/org/dashboard";
            } else if (portal === 'platform') {
                portalName = "Platform Admin";
                portalUrl = "/platform/dashboard";
            } else if (portal === 'campaign-express') {
                portalName = "Campaign Express";
                portalUrl = "/campaign-express/dashboard";
            }

            // Check if there is a local legacy breadcrumb element on the page
            const legacyBreadcrumb = document.querySelector('.breadcrumb-bar, .cr-breadcrumb, .studio-breadcrumb, .breadcrumb-custom, nav[aria-label="breadcrumb"]');
            
            if (legacyBreadcrumb) {
                // Parse the items from the legacy breadcrumb
                const links = legacyBreadcrumb.querySelectorAll('a');
                const activeSpan = legacyBreadcrumb.querySelector('span, .active');
                
                // Add Home/Root
                const rootLi = document.createElement('li');
                rootLi.className = 'breadcrumb-item';
                rootLi.innerHTML = `<a href="${portalUrl}${tidSuffix}"><i class="bi bi-house-door"></i> ${portalName}</a>`;
                list.appendChild(rootLi);
                
                // Process links
                links.forEach(link => {
                    // Skip if it is pointing to the workspace root to avoid duplicates
                    const linkPath = new URL(link.href, window.location.origin).pathname;
                    if (linkPath === portalUrl || linkPath === '/worker/dashboard' || linkPath === '/org/dashboard' || linkPath === '/platform/dashboard') {
                        return;
                    }
                    
                    const li = document.createElement('li');
                    li.className = 'breadcrumb-item';
                    
                    // Propagate tid to the legacy link
                    let href = link.getAttribute('href');
                    if (href && !href.includes('tid=') && tid) {
                        const separator = href.includes('?') ? '&' : '?';
                        href = href + separator + 'tid=' + tid;
                    }
                    
                    li.innerHTML = `<a href="${href}">${link.innerHTML}</a>`;
                    list.appendChild(li);
                });
                
                // Process active item
                if (activeSpan) {
                    const li = document.createElement('li');
                    li.className = 'breadcrumb-item active';
                    li.innerHTML = `<span>${activeSpan.innerHTML}</span>`;
                    list.appendChild(li);
                }
            } else {
                // Always add Home / Portal Root
                const rootLi = document.createElement('li');
                rootLi.className = 'breadcrumb-item';
                rootLi.innerHTML = `<a href="${portalUrl}${tidSuffix}"><i class="bi bi-house-door"></i> ${portalName}</a>`;
                list.appendChild(rootLi);

                // Sub-paths mapping
                let currentPath = `/${portal}`;
                let renderedItems = [];
                for (let i = 1; i < segments.length; i++) {
                    const seg = segments[i];
                    currentPath += `/${seg}`;

                    if (seg === 'manage') {
                        continue;
                    }

                    const li = document.createElement('li');
                    li.className = 'breadcrumb-item';

                    // Format name
                    let name = seg.charAt(0).toUpperCase() + seg.slice(1);
                    let linkUrl = currentPath + tidSuffix;

                    // Specific segments override
                    if (seg === 'modules') {
                        name = "Modules";
                        linkUrl = `/${portal}/modules${tidSuffix}`;
                    } else if (seg === 'reports') {
                        name = "Reports";
                    } else if (seg === 'workers') {
                        name = "Workers";
                    } else if (seg === 'campaigns') {
                        name = "Campaigns";
                    } else if (seg === 'billing') {
                        name = "Billing";
                    } else if (seg === 'orgs') {
                        name = "Organizations";
                    } else if (seg === 'groups') {
                        name = "Groups";
                    } else if (seg === 'preferences') {
                        name = "Preferences";
                    } else if (seg === 'profile') {
                        name = "Profile";
                    } else if (!isNaN(seg)) {
                        // It is a numeric ID (like module ID 12 or org ID 3)
                        // Try to get item name from title/heading
                        const headingEl = document.querySelector('.premium-topbar h1') || document.querySelector('h1') || document.querySelector('h2');
                        let detectedName = "";
                        if (headingEl) {
                            detectedName = headingEl.textContent.replace('Modules /', '').replace('Modules/', '').replace('Platform /', '').replace('Org /', '').trim();
                        }
                        name = detectedName || `ID: ${seg}`;
                        
                        // Link to the groups dashboard or detail page
                        if (segments[i-1] === 'modules') {
                            linkUrl = `/${portal}/modules/${seg}/groups${tidSuffix}`;
                        } else if (segments[i-1] === 'orgs') {
                            linkUrl = `/${portal}/orgs/${seg}${tidSuffix}`;
                        }
                    }

                    li.innerHTML = `<a href="${linkUrl}">${name}</a>`;
                    list.appendChild(li);
                    renderedItems.push({ element: li, linkUrl: linkUrl, name: name });
                }

                // Set the last rendered item as active (if no group is appended)
                const groupId = urlParams.get('group');
                if (renderedItems.length > 0) {
                    const lastItem = renderedItems[renderedItems.length - 1];
                    if (!groupId) {
                        lastItem.element.classList.add('active');
                        lastItem.element.innerHTML = `<span>${lastItem.name}</span>`;
                    } else {
                        lastItem.element.innerHTML = `<a href="${lastItem.linkUrl}">${lastItem.name}</a>`;
                    }
                }

                // Extra leaf segment if we are filtering by group in url (e.g. ?group=12)
                if (groupId) {
                    // Try to find group indicator badge text
                    const groupIndicator = document.getElementById('active-group-indicator') || document.querySelector('[data-group-name]');
                    let groupName = groupIndicator ? groupIndicator.getAttribute('data-group-name') : null;
                    if (!groupName) {
                        const badgeText = document.body.innerHTML.match(/Group:\s*([^<]+)/);
                        if (badgeText) groupName = badgeText[1].trim();
                    }
                    
                    if (groupName) {
                        // Append active group leaf node
                        const groupLi = document.createElement('li');
                        groupLi.className = 'breadcrumb-item active';
                        groupLi.innerHTML = `<span>Group: ${groupName}</span>`;
                        list.appendChild(groupLi);
                    }
                }
            }

            breadcrumbNav.appendChild(list);
            
            // Insert it right downside the header section
            topbar.parentNode.insertBefore(breadcrumbNav, topbar.nextSibling);
        })();
    }
});

// Global Toast System
window.showToast = function(message, type = 'info') {
    let container = document.querySelector('.premium-toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'premium-toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `premium-toast premium-toast-${type}`;
    
    let iconClass = 'bi-info-circle-fill';
    if (type === 'success') iconClass = 'bi-check-circle-fill';
    if (type === 'danger') iconClass = 'bi-exclamation-triangle-fill';

    toast.innerHTML = `
        <div class="premium-toast-content">
            <span class="premium-toast-icon"><i class="bi ${iconClass}"></i></span>
            <span>${message}</span>
        </div>
        <button class="premium-toast-close" onclick="let p = this.parentElement; p.classList.remove('show'); p.classList.add('hide'); setTimeout(() => p.remove(), 500);"><i class="bi bi-x"></i></button>
    `;

    container.appendChild(toast);
    
    // Trigger animation
    setTimeout(() => {
        toast.classList.add('show');
    }, 50);

    // Auto-remove after 4.5 seconds
    setTimeout(() => {
        if (toast && toast.parentElement) {
            toast.classList.remove('show');
            toast.classList.add('hide');
            setTimeout(() => {
                if (toast && toast.parentElement) toast.remove();
            }, 500);
        }
    }, 4500);
};
