SELECT count(*)
FROM aka_title, kind_type, link_type, movie_info, movie_info_idx, movie_keyword, movie_link, title
WHERE kind_type.kind = 'tv series'
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_info_idx.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
