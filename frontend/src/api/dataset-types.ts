import type { operations } from "./schema";

type ContentsQuery = NonNullable<
  operations["list_contents_api_datasets__dataset_id__contents_get"]["parameters"]["query"]
>;
/** 数据集的筛选（后端 `ContentFilter`），浏览、导出共用。 */
export type ContentFilter = Omit<ContentsQuery, "limit" | "offset" | "sort">;
export type ContentSort = NonNullable<ContentsQuery["sort"]>;
