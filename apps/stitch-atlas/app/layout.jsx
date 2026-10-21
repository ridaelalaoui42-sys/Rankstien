import './globals.css';
import '../styles/guides.css';
import '../styles/academy.css';
import '../styles/continue-learning.css';
import SiteHeader from '../components/SiteHeader';
import Footer from '../components/Footer';
const title='Stitch Atlas | Crochet Patterns, Stitches & Handmade Living';
const siteUrl=process.env.NEXT_PUBLIC_SITE_URL || (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : 'http://localhost:3000');
export const metadata={
  metadataBase: new URL(siteUrl),
  title:{default:title, template:'%s | Stitch Atlas'},
  description:'An independent crochet publication in development. Discover thoughtfully illustrated stitch lessons, useful maker tools and a forthcoming collection of original, tested free patterns.',
  applicationName:'Stitch Atlas',
  manifest:'/site.webmanifest',
  icons:{icon:[{url:'/brand/mark.svg',type:'image/svg+xml'}],apple:'/apple-touch-icon.png'},
  openGraph:{type:'website',siteName:'Stitch Atlas',title,description:'A future home for genuine free crochet patterns, practical stitch learning and quiet creative inspiration.',images:[{url:'/og-cover.jpg',width:900,height:600,alt:'Stitch Atlas crochet editorial brand'}]},
  twitter:{card:'summary_large_image'},
  robots:{index:false,follow:false},
};
export default function RootLayout({children}) {
  return <html lang="en"><body><a className="skip-link" href="#main">Skip to content</a><div className="announcement">IN THE MAKING <span aria-hidden="true">✳</span> A NEW HOME FOR ORIGINAL CROCHET, STITCH BY STITCH</div><SiteHeader/>{children}<Footer/></body></html>;
}
