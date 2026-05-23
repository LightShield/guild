/** @type {import('tailwindcss').Config} */
export default {
	content: ['./src/**/*.{html,js,svelte,ts}'],
	theme: {
		fontFamily: {
			mono: ['"JetBrains Mono"', '"Cascadia Code"', 'Consolas', 'monospace'],
		},
		extend: {
			borderRadius: {
				DEFAULT: '0.15rem',
				sm: '0.1rem',
				md: '0.15rem',
				lg: '0.2rem',
				xl: '0.25rem',
				'2xl': '0.3rem'
			},
			colors: {
				guild: {
					50: '#f0f9ff',
					100: '#e0f2fe',
					200: '#bae6fd',
					300: '#7dd3fc',
					400: '#38bdf8',
					500: '#0ea5e9',
					600: '#0284c7',
					700: '#0369a1',
					800: '#075985',
					900: '#0c4a6e',
					950: '#082f49'
				}
			},
			animation: {
				'pulse-dot': 'pulse-dot 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
				'fade-in': 'fade-in 0.35s ease-out both',
				'slide-up': 'slide-up 0.3s ease-out both',
				'blink': 'blink 1.2s step-end infinite',
			},
			keyframes: {
				'pulse-dot': {
					'0%, 100%': { opacity: '1', transform: 'scale(1)' },
					'50%': { opacity: '0.45', transform: 'scale(0.8)' },
				},
				'fade-in': {
					from: { opacity: '0', transform: 'translateY(5px)' },
					to: { opacity: '1', transform: 'translateY(0)' },
				},
				'slide-up': {
					from: { opacity: '0', transform: 'translateY(8px)' },
					to: { opacity: '1', transform: 'translateY(0)' },
				},
				'blink': {
					'0%, 100%': { opacity: '1' },
					'50%': { opacity: '0' },
				},
			},
			boxShadow: {
				'glow-blue': '0 0 20px rgba(56, 189, 248, 0.3), 0 0 6px rgba(56, 189, 248, 0.15)',
				'glow-green': '0 0 20px rgba(52, 211, 153, 0.3), 0 0 6px rgba(52, 211, 153, 0.15)',
				'glow-sm-blue': '0 0 8px rgba(56, 189, 248, 0.2)',
			}
		}
	},
	plugins: []
};
