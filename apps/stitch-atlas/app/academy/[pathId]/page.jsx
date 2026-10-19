import AcademyPath from '../../../components/AcademyPath.jsx';
import {academyPaths,getAcademyPath} from '../../../lib/academy.mjs';
import {notFound} from 'next/navigation';
export const dynamicParams=false;
export function generateStaticParams(){return academyPaths.map(path=>({pathId:path.id}))}
export async function generateMetadata({params}){const {pathId}=await params,path=getAcademyPath(pathId);return path?{title:`${path.title} | Free Crochet Learning Path`,description:path.description}:{title:'Not found',robots:{index:false}}}
export default async function PathPage({params}){const {pathId}=await params,path=getAcademyPath(pathId);if(!path)notFound();return <AcademyPath path={path}/>}
