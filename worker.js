// Cloudflare Worker для генерации subscription конфигов
// Работает с пулом публичных серверов

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    if (url.pathname === '/sub') {
      const token = url.searchParams.get('token');
      
      if (!token) {
        return new Response('Missing token', { status: 400 });
      }

      // Проверяем токен в Supabase
      const supabaseUrl = env.SUPABASE_URL;
      const supabaseKey = env.SUPABASE_KEY;
      
      const response = await fetch(`${supabaseUrl}/rest/v1/subscriptions?id=eq.${token}`, {
        headers: {
          'apikey': supabaseKey,
          'Authorization': `Bearer ${supabaseKey}`
        }
      });

      const data = await response.json();
      
      if (!data || data.length === 0) {
        return new Response('Invalid token', { status: 404 });
      }

      const subscription = data[0];
      const expiresAt = new Date(subscription.expires_at);
      
      // Проверяем срок действия
      if (expiresAt < new Date()) {
        return new Response('Subscription expired', { status: 403 });
      }

      // Генерируем конфиг с серверами из пула
      const config = generateConfig(subscription);
      
      // Кодируем в base64 для subscription
      const base64Config = btoa(JSON.stringify(config));
      
      return new Response(base64Config, {
        headers: {
          ...corsHeaders,
          'Content-Type': 'text/plain',
          'Subscription-Userinfo': `upload=0; download=0; total=10737418240; expire=${Math.floor(expiresAt.getTime() / 1000)}`
        }
      });
    }

    return new Response('Not found', { status: 404 });
  }
};

function generateConfig(subscription) {
  // Пул публичных серверов (добавь свои)
  const serverPool = [
    {
      address: "87.239.104.97",
      port: 7443,
      password: "Qfw0MqoyNkSvqjRhZ_x5WNM3V_tF6q",
      sni: "plthree.rushtaxi.ru"
    },
    // Добавь сюда все свои публичные серверы
    // {
    //   address: "другой_сервер.com",
    //   port: 443,
    //   password: "другой_пароль",
    //   sni: "другой_sni.com"
    // }
  ];

  // Выбираем серверы для этого пользователя (детерминированно по ID)
  const selectedServers = selectServersForUser(subscription.id, serverPool);

  const baseConfig = {
    "dns": {
      "tag": "dns",
      "servers": [
        "https://cloudflare-dns.com/dns-query",
        "1.1.1.1"
      ],
      "queryStrategy": "UseIP",
      "disableFallback": true
    },
    "routing": {
      "domainStrategy": "IPIfNonMatch",
      "domainMatcher": "hybrid",
      "rules": [
        {
          "type": "field",
          "inboundTag": ["dns"],
          "outboundTag": "proxy"
        },
        {
          "type": "field",
          "domain": ["geosite:category-ads-all"],
          "outboundTag": "block"
        },
        {
          "type": "field",
          "protocol": ["bittorrent"],
          "outboundTag": "direct"
        },
        {
          "type": "field",
          "domain": [
            "domain:wildberries.ru", "domain:wildberries.by", "domain:wildberries.kz",
            "domain:sberbank.ru", "domain:sber.ru", "domain:ozon.ru",
            "domain:gosuslugi.ru", "domain:yandex.ru", "domain:vk.com",
            "domain:mail.ru", "domain:tinkoff.ru", "domain:avito.ru"
          ],
          "outboundTag": "direct"
        },
        {
          "type": "field",
          "domain": [
            "geosite:youtube", "geosite:telegram", "geosite:netflix",
            "geosite:spotify", "geosite:discord", "geosite:twitch"
          ],
          "outboundTag": "proxy"
        },
        {
          "type": "field",
          "network": "tcp,udp",
          "outboundTag": "proxy"
        }
      ]
    },
    "inbounds": [
      {
        "tag": "socks",
        "port": 10808,
        "listen": "127.0.0.1",
        "protocol": "socks",
        "settings": {
          "udp": true,
          "auth": "noauth"
        },
        "sniffing": {
          "enabled": true,
          "routeOnly": false,
          "destOverride": ["http", "tls", "quic"]
        }
      },
      {
        "tag": "http",
        "port": 10809,
        "listen": "127.0.0.1",
        "protocol": "http",
        "settings": {
          "allowTransparent": false
        },
        "sniffing": {
          "enabled": true,
          "routeOnly": false,
          "destOverride": ["http", "tls", "quic"]
        }
      }
    ],
    "outbounds": []
  };

  // Добавляем выбранные серверы в outbounds
  selectedServers.forEach((server, index) => {
    baseConfig.outbounds.push({
      "tag": index === 0 ? "proxy" : `proxy-${index}`,
      "protocol": "trojan",
      "settings": {
        "servers": [{
          "address": server.address,
          "port": server.port,
          "password": server.password
        }]
      },
      "streamSettings": {
        "network": "tcp",
        "security": "tls",
        "tlsSettings": {
          "serverName": server.sni,
          "allowInsecure": false,
          "fingerprint": "ios",
          "alpn": ["h2", "http/1.1"]
        }
      }
    });
  });

  // Добавляем direct и block
  baseConfig.outbounds.push(
    {
      "tag": "direct",
      "protocol": "freedom",
      "settings": {"domainStrategy": "AsIs"}
    },
    {
      "tag": "block",
      "protocol": "blackhole"
    }
  );

  // Добавляем балансировщик если серверов больше 1
  if (selectedServers.length > 1) {
    const proxyTags = selectedServers.map((_, i) => i === 0 ? "proxy" : `proxy-${i}`);
    baseConfig.balancers = [{
      "tag": "balancer",
      "selector": proxyTags,
      "strategy": {
        "type": "leastPing"
      }
    }];
  }

  return baseConfig;
}

// Детерминированный выбор серверов для пользователя
function selectServersForUser(userId, serverPool) {
  // Хешируем userId для получения числа
  let hash = 0;
  for (let i = 0; i < userId.length; i++) {
    hash = ((hash << 5) - hash) + userId.charCodeAt(i);
    hash = hash & hash;
  }
  
  // Определяем сколько серверов выдать (от 2 до всех доступных)
  const minServers = Math.min(2, serverPool.length);
  const maxServers = Math.min(4, serverPool.length);
  const numServers = minServers + (Math.abs(hash) % (maxServers - minServers + 1));
  
  // Выбираем серверы детерминированно
  const selected = [];
  const poolCopy = [...serverPool];
  
  for (let i = 0; i < numServers && poolCopy.length > 0; i++) {
    const index = Math.abs(hash + i) % poolCopy.length;
    selected.push(poolCopy[index]);
    poolCopy.splice(index, 1);
  }
  
  return selected;
}
