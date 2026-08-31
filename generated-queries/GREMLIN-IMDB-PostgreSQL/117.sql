SELECT count(*)
FROM aka_title, complete_cast, info_type, keyword, link_type, movie_info, movie_keyword, movie_link, person_info, title
WHERE aka_title.season_nr = 2
  AND aka_title.movie_id = title.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id;
