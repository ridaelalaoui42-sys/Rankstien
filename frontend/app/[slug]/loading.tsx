
export default function Loading() {
  return (
    <div className="min-h-screen bg-white">
      {/* Skeleton for Header */}
      <div className="container mx-auto px-8 md:px-12 pt-12 pb-16 text-center max-w-5xl animate-pulse">
        <div className="h-4 w-48 bg-gray-100 mx-auto mb-10 rounded-full" />
        <div className="h-16 md:h-24 bg-gray-100 w-3/4 mx-auto mb-10 rounded-2xl" />
        <div className="flex flex-col items-center gap-8">
          <div className="h-4 w-64 bg-gray-50 rounded-full" />
          <div className="h-10 w-40 bg-gray-50 rounded-full" />
        </div>
      </div>

      {/* Skeleton for Featured Image */}
      <div className="container mx-auto px-8 mb-16 max-w-7xl animate-pulse">
        <div className="aspect-[16/9] md:aspect-[21/9] bg-gray-100 rounded-[2.5rem] md:rounded-[4rem]" />
      </div>

      {/* Skeleton for Content Area */}
      <div className="container mx-auto px-8 md:px-12 animate-pulse">
        <div className="max-w-[90rem] mx-auto flex flex-col lg:flex-row gap-16 lg:gap-24">
          <div className="flex-1 space-y-8">
            <div className="h-8 w-full bg-gray-50 rounded-lg" />
            <div className="h-8 w-5/6 bg-gray-50 rounded-lg" />
            <div className="h-64 w-full bg-gray-100 rounded-3xl" />
            <div className="space-y-4">
              <div className="h-4 w-full bg-gray-50 rounded" />
              <div className="h-4 w-full bg-gray-50 rounded" />
              <div className="h-4 w-3/4 bg-gray-50 rounded" />
            </div>
          </div>
          <div className="hidden lg:block w-[350px] space-y-8">
            <div className="h-64 w-full bg-gray-50 rounded-3xl" />
            <div className="h-96 w-full bg-gray-50 rounded-3xl" />
          </div>
        </div>
      </div>
    </div>
  );
}
