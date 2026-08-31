SELECT count(*)
FROM aka_title, complete_cast, info_type, keyword, kind_type, movie_info, movie_keyword, movie_link, title
WHERE info_type.info = 'LD production country'
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
