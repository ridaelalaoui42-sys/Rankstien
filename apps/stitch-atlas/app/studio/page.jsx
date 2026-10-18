import EditorialStudio from '../../components/EditorialStudio';
export const metadata={title:'Private Editorial Studio',description:'Authorized Stitch Atlas editorial workspace. Not a public pattern library.',robots:{index:false,follow:false}};
export default function EditorialWorkspace(){return <main id="main"><section className="container studio-container"><EditorialStudio/></section></main>}
